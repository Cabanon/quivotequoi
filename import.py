import requests
import json
import csv
import io
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime as dt, date, timezone
from dateutil.parser import parse as parsedate
from pathlib import Path
from enum import StrEnum, auto
from multiprocessing import Pool

import typer
import lzip
import bs4
from sqlalchemy.orm import Session
from sqlalchemy import select
from tqdm import tqdm

from database import engine
from models import Base, Member, Group, Vote, Position, Amendment

Base.metadata.create_all(bind=engine)

PARLTRACK_DUMPS_URL = "https://parltrack.org/dumps/"


class Data(StrEnum):
    MEMBERS = auto()
    PROCEDURES = auto()
    SUBJECTS = auto()
    AMENDMENTS = auto()
    VOTES = auto()
    RCV = auto()
    ATTENDANCES = auto()


class ReadableIterator(io.IOBase):
    def __init__(self, it):
        self.it = iter(it)

    def read(self, n):
        return next(self.it, b'')
    
    def readable(self):
        return True


def normalize(s):
    return unicodedata.normalize("NFD", s).encode("ASCII", "ignore").lower()

def parse_subjects(subjects):
    codes = []
    for subject in subjects:
        code = subject['text'].split(' ')[0]
        if not any(c for c in codes if code in c):
            codes.append(code)
    return codes

def fetch_proc(ref):
    sess = requests.Session()
    sess.cookies.update({ 'oeilLanguage': 'fr'})
    url = f'https://oeil.secure.europarl.europa.eu/oeil/popups/ficheprocedure.json?reference={ref}&l=fr'
    try:
        res = sess.get(url)
        fiche = json.loads(res.text)['procedure']
        proc = fiche['oeilSpecificData']
        return dict(
            reference=proc['reference'],
            date=proc['events'][0]['date'],
            title=proc['titles'][0]['text'].replace('&nbsp;', ' '),
            type=fiche['identifier']['typeProcedure'],
            subject=parse_subjects(proc['subjects']),
            status=proc['stageReached'],
            url=url
        )
    except Exception as error:
        print(url, error)

def download_if_new(filename):
    url = PARLTRACK_DUMPS_URL + filename
    res = requests.get(url, stream=True)
    local_file = Path(filename)
    if local_file.exists():
        url_dt = parsedate(res.headers["last-modified"])
        file_dt = dt.fromtimestamp(local_file.stat().st_mtime, tz=timezone.utc)
        if url_dt < file_dt:
            print(f"No new version of {filename}. Skipping download.")
            return
    print("Downloading new version...")
    bar = tqdm(
        total=int(res.headers["content-length"]),
        desc=f"Downloading {filename} from Parltrack",
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        miniters=1,
    )
    with local_file.open("wb") as f:
        for chunk in res.iter_content(chunk_size=1024):
            size = f.write(chunk)
            bar.update(size)


def read_json(filename):
    filename += '.lz'
    download_if_new(filename)
    stream = ReadableIterator(lzip.decompress_file_iter(filename))
    print(f'Processing {filename}...')
    with io.TextIOWrapper(stream) as f:
        for line in f:
            if line == "]":
                return
            yield json.loads(line[1:])

def main(data: Data):
    start_date = date(2019, 7, 2)
    end_date = date(2024, 7, 15)
    match data:
        case Data.MEMBERS:
            members = []
            for mep in read_json('ep_meps.json'):
                if 'Constituencies' in mep:
                    constituencies = list(c for c in mep['Constituencies'] if c and c.get('term') == 9 and c['country'] == 'France')
                    if constituencies:
                        members.append(
                            dict(
                                id=mep["UserID"],
                                full_name=mep["Name"]["full"],
                                last_name=mep["Name"]["family"],
                                constituencies=json.dumps(constituencies),
                            )
                        )
            with open('_data/members.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=members[0].keys())
                writer.writeheader()
                writer.writerows(members)

        case Data.ATTENDANCES:
            with open('_data/members.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                meps = list(mep for mep in reader)

            response = requests.get('https://www.europarl.europa.eu/plenary/fr/ajax/getSessionCalendar.html?family=PV&termId=9').json()
            start_date = dt.strptime(response['startDate'], '%d/%m/%Y').date()
            end_date = dt.strptime(response['endDate'], '%d/%m/%Y').date()
            attendances = []
            for sess in response['sessionCalendar']:
                sess_date = date(*map(int, (sess['year'], sess['month'], sess['day'])))
                if start_date < sess_date < end_date and sess['url']:
                    try:
                        url = sess['url'].replace('TOC', 'ATT')
                        request = requests.get(url)
                        request.raise_for_status()
                    except requests.HTTPError:
                        print(sess)
                        continue
                    html = bs4.BeautifulSoup(request.content)

                    attended = []
                    for content in html.select('p.contents'):
                        if ':' not in content.text:
                            attended.extend(content.text.split(', '))
                    
                    for mep in meps:
                        if mep['full_name'].title() in attended:
                            attend = True
                        elif key:=mep['last_name'].title() in attended:
                            attend = True
                        else:
                            attend = False

                        attendances.append(dict(
                            date=sess_date,
                            member_id=mep['id'],
                            attend=attend,
                        ))

            with open('_data/attendances.csv', 'w') as csvfile:
                fieldnames = attendances[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(attendances)

        case Data.SUBJECTS:
            sess = requests.Session()
            sess.get('https://oeil.secure.europarl.europa.eu/oeil/search/search.do')
            sess.cookies.update({ 'oeilLanguage': 'fr' })
            html = sess.get('https://oeil.secure.europarl.europa.eu/oeil/search/facet.do?facet=internetSubject_s').text
            soup = bs4.BeautifulSoup(html)
            subject_tree = []
            for a in soup.find_all('a'):
                key, subject = str(a.attrs['title']).split(' ', 1)
                subject_tree.append({ 'code': key, 'name': subject})
            with open('_data/subjects.json', 'w') as f:
                json.dump(subject_tree, f, indent=2)

        case Data.PROCEDURES:
            with open('_data/votes.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                refs = set(vote['procedure_ref'] for vote in reader)

            from tqdm.contrib.concurrent import thread_map

            procs = thread_map(fetch_proc, refs, max_workers=4)

            with open('_data/procedures.csv', 'w') as csvfile:
                fieldnames = procs[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filter(None, procs))

        case Data.VOTES:
            with open('_data/members.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                mepids = list(mep['id'] for mep in reader)

            with open('_data/votes.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['id', 'date', 'procedure_ref', 'title', 'positions'])
                writer.writeheader()

                for pv in read_json("ep_votes.json"):
                    vote_date = dt.fromisoformat(pv["ts"]).date()
                    if (
                        start_date < vote_date < end_date
                        and "epref" in pv.keys()
                        and len(pv["epref"]) == 1
                        and "votes" in pv.keys()
                    ):
                        vote = dict(
                            id=pv["voteid"],
                            date=vote_date,
                            procedure_ref=pv["epref"][0],
                            title=pv["title"],
                        )
                        positions = []
                        for position, votes in pv["votes"].items():
                            for meps in votes["groups"].values():
                                for mep in meps:
                                    if str(mep["mepid"]) in mepids:
                                        positions.append(
                                            dict(
                                                member_id=mep["mepid"],
                                                position=position,
                                            )
                                        )
                        vote['positions'] = json.dumps(positions)
                        writer.writerow(vote)

        case Data.AMENDMENTS:
            with Session(engine) as session:
                session.query(Amendment).delete()
                for amd in read_json('ep_plenary_amendments.json'):
                    if 'vote_ids' in amd:
                        for vote_id in amd['vote_ids']:
                            vote = session.get(Vote, vote_id)
                            if not vote: break
                            vote.amendment_id = amd['id']
                        amendment = Amendment(
                            id=amd["id"],
                            procedure_ref=amd["reference"],
                        )
                        if "old" in amd:
                            amendment.old = " ".join(amd["old"])
                        if "new" in amd:
                            amendment.new = " ".join(amd["new"])
                        session.add(amendment)
                print(f'{len(session.new)} amendments will be imported')
                session.commit()


if __name__ == "__main__":
    typer.run(main)
