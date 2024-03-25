import requests
import json
import csv
import io
import unicodedata
from datetime import datetime as dt, date, timezone
from dateutil.parser import parse as parsedate
from pathlib import Path
from enum import StrEnum, auto

import typer
import lzip
import bs4
from sqlalchemy.orm import Session
from sqlalchemy import select
from tqdm import tqdm
from dotted_dict import DottedDict

from database import engine
from models import Base, Member, Group, Procedure, Vote, Position, Amendment

Base.metadata.create_all(bind=engine)

PARLTRACK_DUMPS_URL = "https://parltrack.org/dumps/"


class Data(StrEnum):
    MEMBERS = auto()
    PROCEDURES = auto()
    SUBJECTS = auto()
    AMENDMENTS = auto()
    VOTES = auto()
    RCV = auto()


class ReadableIterator(io.IOBase):
    def __init__(self, it):
        self.it = iter(it)

    def read(self, n):
        return next(self.it, b'')
    
    def readable(self):
        return True


def normalize(s):
    return unicodedata.normalize("NFD", s).encode("ASCII", "ignore").lower()


def proc_type(proc):
    if "type" in proc:
        t = proc["type"]
    if "Type of document" in proc:
        t = proc["Type of document"]
    return t[0] if type(t) == list else t


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


def party_from_str(s):
    match s:
        case "Agir - La Droite constructive" | "Liste Renaissance" | 'La République en marche' | "Liste L'Europe Ensemble":
            return "Renaissance"
        case 'Mouvement Radical Social-Libéral':
            return "Parti Radical"
    return s


def main(data: Data):
    start_date = date(2019, 7, 2)
    end_date = date(2024, 7, 15)
    match data:
        case Data.MEMBERS:
            with Session(engine) as session:
                session.query(Member).delete()
                for mep in read_json('ep_meps.json'):
                    if mep['active'] and 'Constituencies' in mep:
                        current = next(
                            c for c in mep['Constituencies']
                            if dt.fromisoformat(c['start']) < dt.now() < dt.fromisoformat(c['end'])
                        )
                        if current["country"] == "France":
                            group = next(
                                c for c in mep['Groups']
                                if dt.fromisoformat(c['start']) < dt.now() < dt.fromisoformat(c['end'])
                            )
                            session.add(
                                Member(
                                    id=mep["UserID"],
                                    full_name=mep["Name"]["full"],
                                    group=Group.from_str(group["groupid"]),
                                    party=party_from_str(current['party']),
                                )
                            )
                print(f'{len(session.new)} members will be imported')
                session.commit()

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
            with open('_data/procedures.csv', 'w') as csvfile, Session(engine) as session:
                fieldnames = ['reference', 'title', 'type', 'date', 'subject', 'url', 'status']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                procedure_refs = list(session.scalars(select(Vote.procedure_ref)))
                subjects = set()
                for doss in read_json("ep_dossiers.json"):
                    if "events" in doss:
                        doss_date = dt.fromisoformat(
                            doss["events"][0]["date"]
                        ).date()
                        if start_date < doss_date < end_date:
                            proc = doss["procedure"]
                            if proc['reference'] in procedure_refs:
                                subjects.update(proc['subject'].items())
                                try:
                                    writer.writerow(
                                        dict(
                                            reference=proc["reference"],
                                            title=proc["title"],
                                            type=Procedure.Type.from_str(proc_type(proc)),
                                            date=doss_date,
                                            subject=json.dumps(list(proc['subject'].keys())),
                                            url=doss['meta']['source'],
                                            status=proc['stage_reached'] if 'stage_reached' in proc else proc['Stage reached']
                                        )
                                    )
                                except:
                                    print(proc)

        case Data.VOTES:
            with Session(engine) as session:
                session.query(Vote).delete()
                session.query(Position).delete()
                mepids = list(session.scalars(select(Member.id)))
                votes_to_add = []
                for pv in read_json("ep_votes.json"):
                    vote_date = dt.fromisoformat(pv["ts"]).date()
                    if (
                        start_date < vote_date < end_date
                        and "epref" in pv.keys()
                        and len(pv["epref"]) == 1
                        and "votes" in pv.keys()
                    ):
                        vote = Vote(
                            id=pv["voteid"],
                            date=vote_date,
                            procedure_ref=pv["epref"][0],
                            title=pv["title"],
                        )
                        positions = []
                        for position, votes in pv["votes"].items():
                            for meps in votes["groups"].values():
                                for mep in meps:
                                    if mep["mepid"] in mepids:
                                        positions.append(
                                            dict(
                                                member_id=mep["mepid"],
                                                position=Position.Position.from_str(position),
                                            )
                                        )
                        vote.positions = positions
                        votes_to_add.append(vote)
                session.add_all(votes_to_add)
                print(f'{len(votes_to_add)} votes will be imported')
                session.commit()
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
