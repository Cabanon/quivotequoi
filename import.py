import json
import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime as dt, date, timezone
from dateutil.parser import parse as parsedate
from pathlib import Path
from enum import StrEnum, auto
from itertools import batched

import typer
import lzip
import bs4
import requests
from requests_cache import CachedSession
import pdfplumber as pp
from tqdm import tqdm

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
            subjects=json.dumps(parse_subjects(proc['subjects'])),
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


def extract_table(page):
    v_lines = (0, page.width / 2, page.width)
    table = page.extract_table({
        "explicit_vertical_lines": v_lines,
        "vertical_strategy": "explicit",
        "horizontal_strategy": "text",
        "snap_tolerance": 5,
        "intersection_tolerance": page.width,
    })
    if table:
        return table
    return []


def extract_amendments(table):
    nr = None
    start = False
    old = ''
    new = ''
    for row in table:
        if row[0].startswith('Amendement'):
            if nr and (old or new):
                yield dict(nr=nr, old=old.strip(), new=new.strip())
            try:
                nr = re.findall(r'\d+', row[0])[0]
            except:
                continue
            start = False
            old = new = ''
        elif row[1].startswith('Amendement'):
            start = True
        elif any(re.search(pattern, ''.join(row)) for pattern in (r'\d+.\d+.\d+', r'AM\\', r'PE\d{3}.\d{3}', r'\bFR\b', 'Unie dans la diversité', 'Or. en')):
            continue
        elif 'http' in row[0] or 'Justification' in ''.join(row):
            start = False
        elif start:
            old += row[0] + ' '
            new += row[1] + ' '
        else:
            continue
    if nr and (old or new): yield dict(nr=nr, old=old.strip(), new=new.strip())


EP_URL = 'https://www.europarl.europa.eu'


def fetch_amendments(doc):
    parts = doc.split('-')
    nr, year = parts[-1].split('/')
    if len(parts) == 3:
        url = f'https://www.europarl.europa.eu/doceo/document/RC-9-{year}-{nr}_FR.html'
    else:
        url = f'https://www.europarl.europa.eu/doceo/document/{parts[0][0]}-9-{year}-{nr}_FR.html'
    session = CachedSession()
    html = bs4.BeautifulSoup(session.get(url).content)
    amendments = []
    if amd_data := html.find(id='amdData'):
        for a in amd_data.find_all('a', attrs={'aria-label': 'pdf'}):
            pdf_url = EP_URL + a.attrs['href']
            tmp = io.BytesIO(requests.get(pdf_url).content)
            pdf = pp.open(tmp)
            for amd in extract_amendments([row for table in map(extract_table, pdf.pages) for row in table]):
                amd.update(dict(doc=doc, url=pdf_url))
                amendments.append(amd)
    return amendments


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
                writer = csv.DictWriter(csvfile, fieldnames=['id', 'date', 'procedure_ref', 'doc', 'amendment', 'positions'])
                writer.writeheader()

                for pv in read_json("ep_votes.json"):
                    vote_date = dt.fromisoformat(pv["ts"]).date()
                    if (
                        start_date < vote_date < end_date
                        and all(key in pv.keys() for key in ('epref', 'votes'))
                        and len(pv["epref"]) == 1
                    ):  
                        title = pv['title'].lower()
                        parts = re.split(r'\s+-\s+', title)
                        try:
                            doc = re.search(r'(RC-)?(A|B|C)[0-9]-[0-9]{4}\/[0-9]{4}', title.upper())[0]
                        except:
                            print('Numéro de procédure introuvable dans:', title)
                            continue
                        if match := re.search(r'am\s+(\w+)', title):
                            try:
                                amendment = int(match[1])
                            except:
                                continue
                        elif any(re.search(pattern, title) for pattern in ('résolution', 'décision', 'vote unique', 'vote final', r'proposition de( la)? commissi?on')):
                            amendment = None
                        elif '§' in title or 'considérant' in title:
                            continue
                        else:
                            continue

                        vote = dict(
                            id=pv["voteid"],
                            date=vote_date,
                            amendment=amendment,
                            procedure_ref=pv["epref"][0],
                            doc=doc,
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
            from tqdm.contrib.concurrent import thread_map

            with open('_data/votes.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                docs = set(vote['doc'] for vote in reader)

            with open('_data/amendments.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['doc', 'nr', 'old', 'new', 'url'])
                writer.writeheader()
                
                for batch in batched(docs, 200):
                    amendments = [amd for amendments in thread_map(fetch_amendments, batch, max_workers=4) for amd in amendments]
                    writer.writerows(amendments)

if __name__ == "__main__":
    typer.run(main)
