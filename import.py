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
import country_converter as coco

PARLTRACK_DUMPS_URL = "https://parltrack.org/dumps/"


class Data(StrEnum):
    MEMBERS = auto()
    PROCEDURES = auto()
    SUBJECTS = auto()
    COUNTRIES = auto()
    DOCS = auto()
    VOTES = auto()
    VOTINGS = auto()
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

def parse_committees(players):
    players = [com.get('europeanParliamentPlayer') for com in players]
    codes = [player.get('committeeCode') for player in players if player is not None]
    return [code for code in codes if code is not None]

def fetch_proc(ref):
    sess = CachedSession()
    sess.cookies.update({ 'oeilLanguage': 'fr'})
    url = f'https://oeil.secure.europarl.europa.eu/oeil/popups/ficheprocedure.do?reference={ref}&l=fr'
    try:
        res = sess.get(url.replace('.do', '.json'))
        res.raise_for_status()
    except requests.HTTPError:
        return {}
    fiche = json.loads(res.text)['procedure']
    proc = fiche['oeilSpecificData']
    if len(proc['events']) == 0:
        return {}
    html = bs4.BeautifulSoup(sess.get(url.replace('fr', 'en')).content, features="lxml")
    tag = html.find(string='Subject')
    subjects = set()
    if tag:
        for elem in tag.parent.next_siblings:
            match elem.name:
                case None:
                    subject = elem.text.strip().split(' ')[0]
                    if subject:
                        subjects.add(subject)
                case 'strong':
                    break
    else:
        print(url)
    tag = html.find(string='Geographical area')
    countries = set()
    if tag:
        for elem in tag.parent.next_siblings:
            match elem.name:
                case None:
                    country = elem.text.strip().split(',')[0]
                    if country:
                        countries.add(coco.convert(country, to='ISO2', not_found=None))
                case 'strong':
                    break
    for subject in list(subjects):
        parts = subject.split('.')
        for i in range(len(parts)):
            subjects.add('.'.join(parts[:i+1]))
    return dict(
        reference=proc['reference'],
        date=proc['events'][0]['date'],
        title=proc['titles'][0]['text'].replace('&nbsp;', ' '),
        type=fiche['identifier']['typeProcedure'],
        subjects=json.dumps(list(subjects)),
        countries=json.dumps(list(countries)),
        committees=json.dumps(parse_committees(proc['players'])),
        docs=json.dumps([doc['reference'] for doc in proc['documentReferences']]),
        status=proc.get('stageReached'),
        url=url
    )

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


def flag_from_iso(code):
    return chr(0x1f1a5 + ord(code[0])) + chr(0x1f1a5 + ord(code[1]))


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
                nr = int(re.search(r'\d+', row[0])[0])
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


def fetch_doc(doc):
    parts = doc.split('-')
    nr, year = parts[-1].split('/')
    if len(parts) == 3:
        url = f'https://www.europarl.europa.eu/doceo/document/RC-9-{year}-{nr}_FR.html'
    else:
        url = f'https://www.europarl.europa.eu/doceo/document/{parts[0][0]}-9-{year}-{nr}_FR.html'
    session = CachedSession()
    try:
        request = session.get(url)
        request.raise_for_status()
    except requests.HTTPError:
        return {}
    html = bs4.BeautifulSoup(request.content)
    amendments = []
    try:
        procedure = html.find(string=re.compile(r'[0-9]{4}/[0-9]{4}\([A-Z]{3}\)'))
    except:
        print(url)
        return None
    if amd_data := html.find(id='amdData'):
        for a in amd_data.find_all('a', attrs={'aria-label': 'pdf'}):
            pdf_url = EP_URL + a.attrs['href']
            tmp = io.BytesIO(session.get(pdf_url).content)
            pdf = pp.open(tmp)
            for amd in extract_amendments([row for table in map(extract_table, pdf.pages) for row in table]):
                amendments.append(amd)
    return dict(ref=doc, procedure=procedure, amendments=json.dumps(amendments), url=url)


def process_table(table):
    rows = []
    rowspans = {}
    col_nb = int(table.find('COLGROUP').get('COLNB'))
    for tr in table.findall('TBODY/TR'):
        row = []
        i = 0
        while i < col_nb:
            td = tr.find(f"TD[@COLNAME='C{i+1}']")
            if td is not None:
                row.append(', '.join(td.itertext()))
                if 'COLSPAN' in td.keys() and len(rows) > 0: #skip colspan in header
                    cols_to_add = int(td.get('COLSPAN'))-1
                    row.extend(cols_to_add*[None])
                if 'ROWSPAN' in td.keys():
                    rowspans[i] = int(td.get('ROWSPAN'))-1
            elif i in rowspans:
                rowspan = rowspans[i]
                row.append(rows[-1][i])
                if rowspan == 1:
                    del rowspans[i]
                else:
                    rowspans[i] = rowspan-1 
            else:
                row.append(None)
            i+=1
        rows.append(row)
    if len(rows) == 0:
        return []
    header = rows[0]
    return [{col_name.replace('\t', ''): row[i] for i, col_name in enumerate(header) if col_name} for row in rows[1:]]


def parse_amendment(subject, amd):
    subject = subject.lower()
    if 'rejet' in subject:
        return 'REJECTION', None
    elif any(word in subject for word in ('résolution', 'décision', 'vote unique', 'vote final', 'proposition', 'motion', 'resolution')):
        return 'ADOPTION', None
    elif amd == '§':
        return 'SEPARATE', None
    elif amd:
        return 'AMENDMENT', amd
    else:
        return 'PRIMARY', None


def parse_result(result):
    match result:
        case '+':
            return 'ADOPTED'
        case '-' | '—':
            return 'REJECTED'
        case '↓':
            return 'LAPSED'
    return result

    
def extract_split(text):
    match = re.search(r'(\d+)', text or '')
    return match[1] if match else None

DOC_RE = r'(RC-)?(A|B|C)[0-9]-[0-9]{4}\/[0-9]{4}'
def extract_doc(text):
    match = re.search(DOC_RE, text.upper())
    return match[0] if match else None


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
        
        case Data.COUNTRIES:
            with open('_data/procedures.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                codes = set(code for proc in reader for code in json.loads(proc['countries']))

            with open('iso-3166_country_french.json') as f:
                iso_map = json.load(f)

            countries = []
            for code in codes:
                flag = name = None
                match code:
                    case 'ACP countries':
                        name = "Pays d'Afrique, Caraïbes et Pacifique"
                        flag = '🌍'
                    case 'Tibet':
                        name = code
                        flag = '🇷🇪'
                    case 'Atlantic Ocean area':
                        name = 'Océan Atlantique'
                        flag = '🌊'
                    case 'Mediterranean Sea area':
                        name = 'Mer Méditerranée'
                        flag = '🐬'
                    case 'Baltic Sea area':
                        name = 'Mer Baltique'
                        flag = '🦭'
                    case 'Black Sea area':
                        name = 'Mer Noire'
                        flag = '🐟'
                    case 'North Sea area':
                        name = 'Mer du Nord'
                        flag = '🐋'
                    case 'Arctic area':
                        name = 'Arctique'
                        flag = '❄️'
                    case 'Caribbean islands':
                        name = 'Caraïbes'
                        flag = '🏝'
                try:
                    if not flag: flag = flag_from_iso(code)
                    if not name: name = iso_map[code]
                except:
                    print('ERROR', code)
                countries.append({ 'code': code, 'flag': flag, 'name': name })
            with open('_data/countries.json', 'w') as f:
                json.dump(countries, f, indent=2, ensure_ascii=False)

        case Data.PROCEDURES:
            sess = CachedSession()
            sess.get('https://oeil.secure.europarl.europa.eu/oeil/search/search.do')
            sess.cookies.update({ 'oeilLanguage': 'fr' })
            urltemplate = 'https://oeil.secure.europarl.europa.eu/oeil/search/result.do?page={}&sort=d&rows=99&:parliamentaryTerm=9ème+législature+2019+-+2024'
            page = 1
            request = sess.get(urltemplate.format(page))
            html = bs4.BeautifulSoup(request.content)

            PROC_RE = r'reference=(.*)&'
            refs = [re.search(PROC_RE, a['href'])[1] for a in html.select('a.reference')]
            from tqdm.contrib.concurrent import thread_map
            procs = []
            while refs:
                procs.extend(thread_map(fetch_proc, refs))
                page += 1
                request = sess.get(urltemplate.format(page))
                html = bs4.BeautifulSoup(request.content)
                refs = [re.search(PROC_RE, a['href'])[1] for a in html.select('a.reference')]

            with open('_data/procedures.csv', 'w') as csvfile:
                fieldnames = procs[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filter(None, procs)) 

        case Data.VOTES:
            session = CachedSession()
            response = session.get('https://www.europarl.europa.eu/plenary/fr/ajax/getSessionCalendar.html?family=PV&termId=9').json()
            start_date = dt.strptime(response['startDate'], '%d/%m/%Y').date()
            end_date = dt.strptime(response['endDate'], '%d/%m/%Y').date()
            IGNORE_URLS = [
                'https://www.europarl.europa.eu/doceo/document/PV-9-2022-03-09-VOT_FR.html',
                'https://www.europarl.europa.eu/doceo/document/PV-9-2022-03-10-VOT_FR.html',
            ]

            with open('_data/votes.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['date', 'doc', 'author', 'type', 'amendment', 'split', 'result', 'votes', 'remarks', 'url'])
                writer.writeheader()
                for sess in response['sessionCalendar']:
                    sess_date = date(*map(int, (sess['year'], sess['month'], sess['day'])))
                    if start_date < sess_date:
                        url = sess['url'].replace('TOC', 'VOT')
                        if not url or url in IGNORE_URLS:
                            continue
                        request = session.get(url.replace('.html', '.xml'))
                        try:
                            request.raise_for_status()
                        except requests.HTTPError:
                            continue
                        xml = ET.fromstring(request.content)
                        if sess_date < date(2024, 1, 16):
                            for vote in xml[0].find('Vote.Results'):
                                doc = rows = None
                                description = vote.find('Vote.Result.Description.Text')
                                table = vote.find('Vote.Result.Table.Results/TABLE')
                                if description and table:
                                    doc = extract_doc(''.join(description.itertext()))
                                    rows = process_table(table)
                                else:
                                    continue
                                for row in rows:
                                    subject = row['Objet'] or ''
                                    doc = extract_doc(subject) or doc
                                    result = parse_result(row['Vote'])
                                    if doc and result not in ['LAPSED', None] and row['AN, etc.'] != 'div':
                                        type, amendment = parse_amendment(subject, row.get('Am n°'))
                                        remarks = row.get('Votes par AN/VE - observations')
                                        try:
                                            splits = remarks.split(', ', 4)
                                            votes = list(map(int, splits[:3]))
                                            remarks = ''.join(splits[3:])
                                        except:
                                            votes = None
                                        writer.writerow(
                                            dict(
                                                doc=doc,
                                                date=sess_date,
                                                author=row.get('Auteur'),
                                                type=type,
                                                split=extract_split(row['AN, etc.']),
                                                amendment=amendment,
                                                result=result,
                                                votes=json.dumps(votes) if votes else None,
                                                remarks=remarks,
                                                url=url,
                                            )
                                        )
                        else: # New XML format on PE website
                            for vote in xml.find('.//votes').findall('vote'):
                                doc = extract_doc(vote.find('label').text or '')
                                for voting in vote.findall('.//voting'):
                                    if voting.get('type') == "TITLE_BLOCK":
                                        doc = extract_doc(voting.find('title').text) or doc
                                    else:
                                        subject = (voting.find('title').text or '') + (voting.find('label').text or '')
                                        rcv = voting.find('rcv/value')
                                        split = extract_split(rcv.text) if (rcv is not None) else None
                                        result = parse_result(voting.get('result'))
                                        if doc and result not in ['LAPSED', None]:
                                            type, amendment = parse_amendment(subject or '', voting.find('amendmentNumber').text)
                                            #if doc == 'A9-0014/2024': print(subject, type)
                                            votes = voting.find('observations').text
                                            writer.writerow(
                                                dict(
                                                    date=sess_date,
                                                    doc=doc,
                                                    author=voting.find('amendmentAuthor').text,
                                                    type=type,
                                                    split=split,
                                                    amendment=amendment,
                                                    result=result,
                                                    votes=json.dumps(list(map(int, votes.split(', ')))) if votes else None,
                                                    url=url,
                                                )
                                            )
                    
        case Data.VOTINGS:
            with open('_data/members.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                mepids = list(mep['id'] for mep in reader)

            with open('_data/votings.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['id', 'date', 'procedure_ref', 'doc', 'type', 'amendment', 'split', 'positions', 'url'])
                writer.writeheader()

                for pv in read_json("ep_votes.json"):
                    vote_date = dt.fromisoformat(pv["ts"]).date()
                    if (
                        start_date < vote_date < end_date
                        and all(key in pv.keys() for key in ('epref', 'votes'))
                        and len(pv["epref"]) == 1
                    ):  
                        title = pv['title'].lower()
                        try:
                            doc = extract_doc(title)
                        except:
                            print('Numéro de procédure introuvable dans:', title)
                            continue
                        match = re.search(r'am\s+(.*)', title)
                        if match:
                            splits = match[1].split('/')

                            try:
                                amendment = int(splits[0])
                            except:
                                amendment = splits[0]

                            try:
                                split = int(splits[1])
                            except:
                                split = None
                        else:
                            amendment, split = None, None
                        type, amendment = parse_amendment(title, amendment)
                        vote = dict(
                            id=pv["voteid"],
                            date=vote_date,
                            type=type,
                            amendment=amendment,
                            split=split,
                            procedure_ref=pv["epref"][0],
                            doc=doc,
                            url=pv['url'],
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

        case Data.DOCS:
            from tqdm.contrib.concurrent import thread_map

            with open('_data/votes.csv') as csvfile:
                reader = csv.DictReader(csvfile)
                docs = set(vote['doc'] for vote in reader)
            
            with open('_data/docs.csv', 'w') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['ref', 'procedure', 'amendments', 'url'])
                writer.writeheader()
                
                for batch in batched(docs, 200):
                    rows = thread_map(fetch_doc, batch, max_workers=4)
                    writer.writerows(row for row in rows if row)

if __name__ == "__main__":
    typer.run(main)
    