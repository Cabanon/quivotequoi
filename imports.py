import json
import csv
import io
import sys
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime as dt, date, timezone, timedelta
from dateutil.parser import parse as parsedate
from pathlib import Path
from enum import StrEnum, auto
from urllib import parse

import typer
import lzip
import bs4
import requests
from requests_cache import CachedSession
import pdfplumber as pp
from tqdm import tqdm
import country_converter as coco

csv.field_size_limit(sys.maxsize)


PARLTRACK_DUMPS_URL = "https://parltrack.org/dumps/"
EP_BASE_URL = "https://www.europarl.europa.eu/doceo/document/"
TERM = 10


class Data(StrEnum):
    MEMBERS = auto()
    PROCEDURES = auto()
    SUBJECTS = auto()
    COUNTRIES = auto()
    DOCS = auto()
    VOTES = auto()
    VOTINGS = auto()
    ATTENDANCES = auto()
    ACTIVITIES = auto()
    NEWS = auto()


class ReadableIterator(io.IOBase):
    def __init__(self, it):
        self.it = iter(it)

    def read(self, n):
        return next(self.it, b"")

    def readable(self):
        return True


def normalize(s):
    return unicodedata.normalize("NFD", s).encode("ASCII", "ignore").lower()


def parse_committees(players):
    players = [com.get("europeanParliamentPlayer") for com in players]
    codes = [player.get("committeeCode") for player in players if player is not None]
    return [code for code in codes if code is not None]


def fetch_proc(ref):
    sess = CachedSession()
    sess.cookies.update({"oeilLanguage": "fr"})
    url = f"https://oeil.secure.europarl.europa.eu/oeil/popups/ficheprocedure.do?reference={ref}&l=fr"
    try:
        request = sess.get(url)
        request.raise_for_status()
        html = bs4.BeautifulSoup(request.content, features="lxml")
    except:
        return {}
    tag = html.find(string="Subject")
    subjects = set()
    if tag:
        for elem in tag.parent.next_siblings:
            match elem.name:
                case None:
                    subject = elem.text.strip().split(" ")[0]
                    if subject:
                        subjects.add(subject)
                case "strong":
                    break
    tag = html.find(string="Geographical area")
    countries = set()
    if tag:
        for elem in tag.parent.next_siblings:
            match elem.name:
                case None:
                    country = elem.text.strip().split(",")[0]
                    if country:
                        countries.add(coco.convert(country, to="ISO2", not_found=None))
                case "strong":
                    break
    for subject in list(subjects):
        parts = subject.split(".")
        for i in range(len(parts)):
            subjects.add(".".join(parts[: i + 1]))
    committees = None
    try:
        committees = [span.text for span in html.find(string="Acteurs principaux").find_next('table').find_all(class_='erpl_badge-committee')]     
    except:
        pass   
    return dict(
        reference=html.find(class_="erpl_title-h1").text.replace("&nbsp;", " "),
        date=parsedate(html.find(string="Evénements clés").find_next('table').select_one('tr:last-child td').text),
        title=html.find(class_="erpl_title-h2").text.replace("&nbsp;", " "),
        type=html.find(string="Type de procédure").find_next('td').text.split(' - ')[0],
        subjects=json.dumps(list(subjects)),
        countries=json.dumps(list(countries)),
        committees=json.dumps(committees),
        docs=json.dumps([td.text for td in html.find(string="Portail de documentation").find_next('table').select('td:nth-child(2)')]),
        status=html.find(string="Statut").find_next('p').text,
        url=url,
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
    filename += ".lz"
    download_if_new(filename)
    stream = ReadableIterator(lzip.decompress_file_iter(filename))
    print(f"Processing {filename}...")
    with io.TextIOWrapper(stream) as f:
        for line in f:
            if line == "]":
                return
            yield json.loads(line[1:])


def extract_table(page):
    v_lines = (0, page.width / 2, page.width)
    table = page.extract_table(
        {
            "explicit_vertical_lines": v_lines,
            "vertical_strategy": "explicit",
            "horizontal_strategy": "text",
            "snap_tolerance": 5,
            "intersection_tolerance": page.width,
        }
    )
    if table:
        return table
    return []


def flag_from_iso(code):
    return chr(0x1F1A5 + ord(code[0])) + chr(0x1F1A5 + ord(code[1]))


def extract_amendments(table):
    with open("_data/members.csv") as csvfile:
        reader = csv.DictReader(csvfile)
        meps = {mep["full_name"].title(): int(mep["id"]) for mep in reader}

    nr = None
    start = False
    old = ""
    new = ""
    authors = []
    map_authors = lambda authors: json.dumps(
        [
            meps[author.strip()]
            for author in " ".join(authors).split(",")
            if author.strip() in meps
        ]
    )
    for row in table:
        if row[0].startswith("Amendement"):
            if nr and (old or new):
                yield dict(
                    nr=nr,
                    old=old.strip(),
                    new=new.strip(),
                    authors=map_authors(authors),
                )
            try:
                nr = int(re.search(r"\d+", row[0])[0])
            except:
                continue
            start = False
            old = new = ""
        elif row[1].startswith("Amendement"):
            start = True
        elif any(
            re.search(pattern, "".join(row))
            for pattern in (
                r"\d+\.\d+\.\d+",
                r"AM\\",
                r"PE\d{3}.\d{3}",
                r"\bFR\b",
                "Unie dans la diversité",
                "Or. en",
            )
        ):
            continue
        elif "http" in row[0] or "Justification" in "".join(row):
            start = False
        elif start:
            old += row[0] + " "
            new += row[1] + " "
        else:
            authors.extend(row)
    if nr and (old or new) and new != "supprimé":
        yield dict(
            nr=nr, old=old.strip(), new=new.strip(), authors=map_authors(authors)
        )


def dicts_to_csv(dicts, filename):
    with open(f"_data/{filename}.csv", "w") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=dicts[0].keys())
        writer.writeheader()
        writer.writerows(dicts)


EP_URL = "https://www.europarl.europa.eu"


def fetch_doc(doc):
    parts = doc.split("-")
    term = parts[-2][1:]
    nr, year = parts[-1].split("/")
    if len(parts) == 3:
        url = f"https://www.europarl.europa.eu/doceo/document/RC-{term}-{year}-{nr}_FR.html"
    else:
        doc_type = parts[0][0]
        url = f"https://www.europarl.europa.eu/doceo/document/{doc_type}-{term}-{year}-{nr}_FR.html"
    session = CachedSession()
    try:
        request = session.get(url)
        request.raise_for_status()
    except requests.HTTPError:
        print(url)
        return doc
    html = bs4.BeautifulSoup(request.content, features="lxml")
    amendments = []
    try:
        procedure = extract_ref(html.find(string=PROC_RE).text)
    except:
        print(url)
        return None
    if amd_data := html.find(id="amdData"):
        for a in amd_data.find_all("a", attrs={"aria-label": "pdf"}):
            pdf_url = EP_URL + a.attrs["href"]
            tmp = io.BytesIO(session.get(pdf_url).content)
            pdf = pp.open(tmp)
            for amd in extract_amendments(
                [row for table in map(extract_table, pdf.pages) for row in table]
            ):
                amd["url"] = pdf_url
                amendments.append(amd)
    return dict(ref=doc, procedure=procedure, url=url), amendments


def process_table(table, header=True):
    rows = []
    rowspans = {}
    col_nb = int(table.find("COLGROUP").get("COLNB"))
    for tr in table.findall("TBODY/TR"):
        row = []
        i = 0
        while i < col_nb:
            td = tr.find(f"TD[@COLNAME='C{i+1}']")
            if td is not None:
                row.append(" ".join(td.itertext()).replace("\xa0", " "))
                if "COLSPAN" in td.keys() and len(rows) > 0:  # skip colspan in header
                    cols_to_add = int(td.get("COLSPAN")) - 1
                    row.extend(cols_to_add * [None])
                if "ROWSPAN" in td.keys():
                    rowspans[i] = int(td.get("ROWSPAN")) - 1
            elif i in rowspans:
                rowspan = rowspans[i]
                row.append(rows[-1][i])
                if rowspan == 1:
                    del rowspans[i]
                else:
                    rowspans[i] = rowspan - 1
            else:
                row.append(None)
            i += 1
        rows.append(row)
    if len(rows) == 0:
        return []
    if header:
        header = rows[0]
        return [
            {
                col_name.replace("\t", ""): row[i]
                for i, col_name in enumerate(header)
                if col_name
            }
            for row in rows[1:]
        ]
    return rows


def get_dates():
    session = CachedSession()
    response = session.get(
        "https://www.europarl.europa.eu/plenary/fr/ajax/getSessionCalendar.html?family=PV&termId=10"
    ).json()
    term_start = dt.strptime(response["startDate"], "%d/%m/%Y").date()
    term_end = dt.strptime(response["endDate"], "%d/%m/%Y").date()
    sessions = set()

    for sess in response["sessionCalendar"]:
        start = date(
            *map(
                int,
                (
                    sess["year"],
                    sess["monthStartDateSession"],
                    sess["dayStartDateSession"],
                ),
            )
        )
        end = date(
            *map(
                int,
                (sess["year"], sess["monthEndDateSession"], sess["dayEndDateSession"]),
            )
        )
        sessions.add((start, end))

    out = []
    for sess_start, sess_end in sessions:
        dates = []
        tmp_date = sess_start
        while term_start <= tmp_date <= term_end and tmp_date <= sess_end:
            dates.append(tmp_date)
            tmp_date += timedelta(days=1)
        out.append((sess_start, dates))
    return out


def parse_group(group):
    match group:
        case "Renew":
            return "RE"
        case "Patriots for Europe Group" | "ENF" | "ID":
            return "P4E"
        case "Europe of Sovereign Nations Group":
            return "ENS"
        case "PPE-DE":
            return "PPE"
        case "The Left":
            return "GUE/NGL"
    return group


def parse_party(party):
    match party:
        case (
            "Renaissance"
            | "Agir - La Droite constructive"
            | "Liste Renaissance"
            | "La République en marche"
            | "Liste L'Europe Ensemble"
        ):
            return "Renaissance", "RE"
        case "Mouvement Radical Social-Libéral":
            return "Parti Radical", "PR"
        case "Europe Écologie" | "Les Écologistes":
            return "Les Écologistes", "EELV"
        case "Rassemblement national":
            return party, "RN"
        case "Les Républicains":
            return party, "LR"
        case "La France Insoumise":
            return party, "LFI"
        case "Mouvement Démocrate":
            return party, "MoDem"
        case "Union des démocrates et indépendants":
            return party, "UDI"
        case "Mouvement conservateur":
            return party, "MC"
        case "Reconquête!":
            return party, "REC"
        case "Indépendant" | "-" | "Sans parti":
            return party, "Indé."
        case "Parti socialiste":
            return party, "PS"
        case "Place publique":
            return party, "PP"
        case "Régions et Peuples Solidaires":
            return party, "R&PS"
        case "Parti Radical":
            return party, "PR"
        case "Horizons":
            return party, "HOR"
        case "Gauche républicaine et socialiste":
            return party, "GRS"
        case "Les centristes":
            return party, "LC"
        case "Divers droite":
            return party, "DVD"
        case "Nouvelle Donne":
            return party, "ND"
        case "Alliance Écologiste Indépendante":
            return party, "AEI"


def parse_author(author):
    if "députés" in author:
        return ("DEPUTEES",)
    elif author == "commission":
        return "COMMISSION", None
    elif match := re.search("[A-Z]{4}", author):
        return "COMMISSION", match[0]
    elif "rapporteur" in author:
        return ("RAPPORTEUR",)
    elif "texte original" in author:
        return ("ORIGINAL",)
    else:
        return "GROUP", list(
            filter(
                bool, (parse_group(part.strip()) for part in re.split(",|\n", author))
            )
        )


def parse_subject(subject, amd):
    subject_lower = subject.lower()
    amd = str(amd).strip()
    if any(word in subject for word in ("rejet", "reject")):
        return subject, None, "REJECTION"
    elif amd == "§" or any(word in amd.lower() for word in ("pc", "amendement oral")):
        pass
    elif amd and amd != "None":
        return subject, amd, "AMENDMENT"
    elif "renvoi" in subject:
        return subject, None, "RETURN"
    elif "résolution" in subject_lower:
        return "Proposition de résolution", None, "ADOPTION"
    elif "vote unique" in subject_lower:
        return "Adoption du texte", None, "ADOPTION"
    elif "procédure d'approbation" in subject_lower:
        return "Procédure d'approbation", None, "ADOPTION"
    elif re.search(r"proposition de la commissi?on", subject_lower):
        return "Proposition de la commission", None, "ADOPTION"
    else:
        pass

    return subject, amd, "IGNORE"


def parse_result(result):
    match result:
        case "+":
            return "ADOPTED"
        case "-" | "—":
            return "REJECTED"
        case "↓":
            return "LAPSED"
    return result


def extract_split(text):
    match = re.search(r"(\d+)", text or "")
    return match[1] if match else None


DOC_RE = r"(RC-)?(A|B|C)[0-9]+-[0-9]{4}\/[0-9]{4}"


def extract_doc(text):
    match = re.search(DOC_RE, text.upper())
    doc = match[0] if match else None
    if doc == "A9-0280/2019":
        doc = "A9-0280/2021"
    return doc


PROC_RE = re.compile(r"[0-9]{4}/[0-9]{4}[A-Z]?\([A-Z]{3}\)?")


def extract_ref(text):
    match = PROC_RE.search(text)
    return match[0] if match else None


LOC_RE = re.compile(
    r"((?:article|alinéa|considérant|après le considérant|§|paragraphe|après le paragraphe|point|après le point|annexe) \w+)"
)


def extract_loc(text):
    matches = LOC_RE.findall(text.lower())
    return ", ".join(filter(bool, matches)) or None


TITLE_RE = re.compile(rf"{LOC_RE.pattern}?[ -,]*(?:am ([\d -,]*\d))?(?:/(\d)\b)?")


def parse_title(text):
    matches = TITLE_RE.findall(text.lower())
    loc = None
    amendment = None
    split = None
    if len(matches):
        groups = [", ".join(filter(bool, i)) or None for i in zip(*matches)]
        loc, amendment, split = groups

    return loc, amendment, split


def main(data: Data):
    match data:
        case Data.MEMBERS:
            members = []
            for mep in read_json("ep_meps.json"):
                if "Constituencies" in mep:
                    constituencies = list(
                        c
                        for c in mep["Constituencies"]
                        if c and c.get("term") == TERM and c["country"] == "France"
                    )
                    if constituencies:
                        for const in constituencies:
                            const["party"], const["partyid"] = parse_party(
                                const["party"]
                            )
                        for group in mep["Groups"]:
                            group["groupid"] = parse_group(group["groupid"])
                        members.append(
                            dict(
                                id=mep["UserID"],
                                full_name=mep["Name"]["full"],
                                last_name=mep["Name"]["family"],
                                constituencies=json.dumps(constituencies),
                                groups=json.dumps(mep["Groups"]),
                            )
                        )
            with open("_data/members.csv", "w") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=members[0].keys())
                writer.writeheader()
                writer.writerows(members)

        case Data.DOCS:
            from tqdm.contrib.concurrent import process_map

            with open("_data/votes.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                docs = {}
                for vote in reader:
                    doc = vote["doc"]
                    ref = vote["ref"]
                    docs[doc] = ref or docs.get(doc, None)

            with (
                open("_data/docs.csv", "w") as docfile,
                open("_data/amendments.csv", "w") as amdfile,
            ):
                docwriter = csv.DictWriter(
                    docfile, fieldnames=["ref", "procedure", "url"]
                )
                docwriter.writeheader()

                amdwriter = csv.DictWriter(
                    amdfile, fieldnames=["doc", "nr", "old", "new", "authors", "url"]
                )
                amdwriter.writeheader()

                for result in process_map(fetch_doc, docs.keys()):
                    amendments = []
                    try:
                        doc, amendments = result
                    except:
                        doc = dict(ref=result, procedure=docs[result])
                    docwriter.writerow(doc)
                    for amd in amendments:
                        amd["doc"] = doc["ref"]
                        amdwriter.writerow(amd)

        case Data.ACTIVITIES:
            with open("_data/members.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                mep_ids = [int(mep["id"]) for mep in reader]

            session = CachedSession()

            activities = []
            all_speeches = []
            explanations = []
            for activity in read_json("ep_mep_activities.json"):
                if activity["mep_id"] in mep_ids:
                    speeches = []
                    if "CRE" in activity:
                        for speech in activity["CRE"]:
                            if speech["term"] == TERM:
                                xml = ET.fromstring(
                                    session.get(
                                        speech["url"].replace(".html", ".xml")
                                    ).text.replace("&nbsp;", " ")
                                )
                                content = [
                                    para.text
                                    for para in xml.findall(".//PARA")
                                    if para.text
                                ]
                                speeches.append(
                                    dict(
                                        member_id=activity["mep_id"],
                                        title=speech["title"],
                                        date=speech["date"],
                                        procedure=(
                                            speech["dossiers"][0]
                                            if "dossiers" in speech
                                            else None
                                        ),
                                        content=json.dumps(content),
                                    )
                                )
                    all_speeches.extend(speeches)

                    if "WEXP" in activity:
                        for exp in activity["WEXP"]:
                            doc = extract_doc(exp["title"])
                            if doc and exp["term"] == TERM:
                                explanations.append(
                                    dict(
                                        member_id=activity["mep_id"],
                                        date=speech["date"],
                                        doc=doc,
                                        content=exp["text"],
                                    )
                                )

                    if "IMOTION" in activity:
                        imotions = [
                            imotion
                            for imotion in activity["IMOTION"]
                            if imotion["term"] == TERM
                        ]
                    else:
                        imotions = None

                    if "REPORT" in activity:
                        reports = [
                            report
                            for report in activity["REPORT"]
                            if report["term"] == TERM
                        ]
                    else:
                        reports = None

                    activities.append(
                        dict(
                            member_id=activity["mep_id"],
                            imotions=len(imotions) if imotions else 0,
                            reports=len(reports) if reports else 0,
                            speeches=len(speeches) if speeches else 0,
                        )
                    )

            dicts_to_csv(activities, "activities")
            dicts_to_csv(explanations, "explanations")
            dicts_to_csv(all_speeches, "speeches")

        case Data.ATTENDANCES:
            with open("_data/members.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                meps = list(mep for mep in reader)

            session = CachedSession()
            attendances = []
            for sess_date in get_dates():
                url = f"{EP_BASE_URL}PV-{TERM}-{sess_date.strftime("%Y-%m-%d")}-ATT_FR.html"
                try:
                    request = session.get(url)
                    request.raise_for_status()
                except requests.HTTPError:
                    print(url)
                    continue
                html = bs4.BeautifulSoup(request.content)

                attended = []
                for content in html.select("p.contents"):
                    if ":" not in content.text:
                        attended.extend(content.text.split(", "))

                for mep in meps:
                    if mep["full_name"].title() in attended:
                        attend = True
                    elif key := mep["last_name"].title() in attended:
                        attend = True
                    else:
                        attend = False

                    attendances.append(
                        dict(
                            date=sess_date,
                            member_id=mep["id"],
                            attend=attend,
                        )
                    )

            with open("_data/attendances.csv", "w") as csvfile:
                fieldnames = attendances[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(attendances)

        case Data.NEWS:
            session = CachedSession()

            news = []
            page = 0
            while True:
                print(page)
                url = f"https://www.europarl.europa.eu/news/fr/page/{page}?contentType=plenary"
                page += 1
                request = session.get(url)
                html = bs4.BeautifulSoup(request.content, features="lxml")
                links = html.find_all("a")
                if links:
                    for a in links:
                        url = a.attrs["href"]
                        request = session.get(url)
                        html = bs4.BeautifulSoup(request.content)
                        title = a.select_one(".ep_name").text
                        spans = html.find_all(string=re.compile("Fiche de procédure"))
                        hrefs = [span.find_parent("a").attrs["href"] for span in spans]
                        refs = [
                            extract_ref(parse.unquote(href)) for href in hrefs if href
                        ]
                        facts = [
                            e.get_text(strip=True)
                            for e in html.select(".ep-a_facts .ep-p_text")
                        ]
                        if refs and facts:
                            news.append(
                                dict(
                                    title=title,
                                    refs=json.dumps(refs),
                                    facts=json.dumps(facts),
                                    url=url,
                                )
                            )
                else:
                    break

            with open("_data/news.csv", "w") as csvfile:
                fieldnames = news[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(news)

        case Data.SUBJECTS:
            sess = requests.Session()
            sess.get("https://oeil.secure.europarl.europa.eu/oeil/search/search.do")
            sess.cookies.update({"oeilLanguage": "fr"})
            html = sess.get(
                "https://oeil.secure.europarl.europa.eu/oeil/search/facet.do?facet=internetSubject_s"
            ).text
            soup = bs4.BeautifulSoup(html)
            subject_tree = []
            for a in soup.find_all("a"):
                key, subject = str(a.attrs["title"]).split(" ", 1)
                subject_tree.append({"code": key, "name": subject})
            with open("_data/subjects.json", "w") as f:
                json.dump(subject_tree, f, indent=2)

        case Data.COUNTRIES:
            with open("_data/procedures.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                codes = set(
                    code for proc in reader for code in json.loads(proc["countries"])
                )

            with open("iso-3166_country_french.json") as f:
                iso_map = json.load(f)

            countries = []
            for code in codes:
                flag = name = None
                match code:
                    case "ACP countries":
                        name = "Pays d'Afrique, Caraïbes et Pacifique"
                        flag = "🌍"
                    case "Tibet":
                        name = code
                        flag = "🇷🇪"
                    case "Atlantic Ocean area":
                        name = "Océan Atlantique"
                        flag = "🌊"
                    case "Mediterranean Sea area":
                        name = "Mer Méditerranée"
                        flag = "🐬"
                    case "Baltic Sea area":
                        name = "Mer Baltique"
                        flag = "🦭"
                    case "Black Sea area":
                        name = "Mer Noire"
                        flag = "🐟"
                    case "North Sea area":
                        name = "Mer du Nord"
                        flag = "🐋"
                    case "Arctic area":
                        name = "Arctique"
                        flag = "❄️"
                    case "Caribbean islands":
                        name = "Caraïbes"
                        flag = "🏝"
                try:
                    if not flag:
                        flag = flag_from_iso(code)
                    if not name:
                        name = iso_map[code]
                except:
                    print("ERROR", code)
                countries.append({"code": code, "flag": flag, "name": name})
            with open("_data/countries.json", "w") as f:
                json.dump(countries, f, indent=2, ensure_ascii=False)

        case Data.PROCEDURES:
            with open("_data/docs.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                refs = set(doc["procedure"] for doc in reader)

            from tqdm.contrib.concurrent import process_map

            procs = process_map(fetch_proc, refs)
            procs = list(filter(bool, procs))

            with open("_data/procedures.csv", "w") as csvfile:
                fieldnames = procs[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filter(None, procs))

        case Data.VOTES:
            processed = set()
            session = CachedSession()

            with open("_data/members.csv") as csvfile:
                reader = csv.DictReader(csvfile)
                mepmap = {
                    mep["last_name"].capitalize(): int(mep["id"]) for mep in reader
                }

            with open("_data/votes.csv", "w") as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "id",
                        "date",
                        "doc",
                        "ref",
                        "subject",
                        "subject_rcv",
                        "author",
                        "type",
                        "amendment",
                        "split",
                        "rcv",
                        "result",
                        "votes",
                        "positions",
                        "url",
                        "url_rcv",
                    ],
                )
                writer.writeheader()
                for sess_date, vote_dates in get_dates():
                    sess_votes = []
                    sess_votings = []
                    for vote_date in vote_dates:
                        print(vote_date)
                        url = f"{EP_BASE_URL}PV-{TERM}-{vote_date.strftime("%Y-%m-%d")}-VOT_FR.xml"
                        request = session.get(url)
                        try:
                            request.raise_for_status()
                        except requests.HTTPError:
                            continue
                        xml = ET.fromstring(request.content)

                        if vote_date < date(2024, 1, 16):
                            for vote in xml[0].find("Vote.Results"):
                                doc = rows = None
                                title = vote.find("Vote.Result.Text.Title").text
                                description = vote.find("Vote.Result.Description.Text")
                                table = vote.find("Vote.Result.Table.Results/TABLE")
                                if description is not None and table is not None:
                                    desc = "".join(description.itertext())
                                    doc = extract_doc(desc)
                                    rows = process_table(table)
                                else:
                                    continue
                                for row in rows:
                                    subject = row["Objet"] or ""
                                    doc = extract_doc(subject) or doc
                                    result = parse_result(row["Vote"])
                                    rcv = row["AN, etc."]
                                    key = (doc, *row.values())
                                    if key in processed:
                                        continue
                                    else:
                                        processed.add(key)
                                    if doc and result is not None and rcv != "div":
                                        amendment = row.get("Am n°")
                                        subject, amendment, type = parse_subject(
                                            subject, amendment
                                        )
                                        remarks = row.get(
                                            "Votes par AN/VE - observations"
                                        )
                                        try:
                                            splits = re.findall(r"\d+", remarks)
                                            votes = list(map(int, splits[:3]))
                                        except:
                                            votes = None
                                        author = row.get("Auteur")
                                        if (
                                            doc == "A9-0337/2023"
                                            and subject == "Article 16, § 3 TUE"
                                        ):
                                            continue
                                        sess_votes.append(
                                            dict(
                                                doc=doc,
                                                sess_date=sess_date,
                                                date=vote_date,
                                                subject=subject,
                                                author=(
                                                    json.dumps(parse_author(author))
                                                    if author
                                                    else None
                                                ),
                                                type=type,
                                                rcv=rcv is not None and "AN" in rcv,
                                                split=extract_split(row["AN, etc."]),
                                                amendment=amendment,
                                                result=result,
                                                votes=(
                                                    json.dumps(votes) if votes else None
                                                ),
                                                # remarks=remarks,
                                                url=url,
                                            )
                                        )

                                table = vote.find("Vote.Result.Table.Requests/TABLE")
                                if table is not None:
                                    rows = process_table(table, header=False)
                                    div = None
                                    amd = None
                                    split = None
                                    for row in rows:
                                        if div:
                                            if amd:
                                                try:
                                                    split = int(
                                                        re.search(
                                                            r"(\d+).*partie", row[0]
                                                        )[1]
                                                    )
                                                except:
                                                    pass
                                            else:
                                                try:
                                                    amd = int(
                                                        re.search(
                                                            r"amendement\s+(\d+)",
                                                            row[0],
                                                        )[1]
                                                    )
                                                except:
                                                    pass
                                        else:
                                            div = "division" in row[0].lower()

                        else:  # New XML format on PE website
                            for vote in xml.find(".//votes").findall("vote"):
                                desc = vote.find("label").text or ""
                                doc = extract_doc(desc)
                                for voting in vote.findall(".//voting"):
                                    subject = (
                                        (voting.find("title").text or "")
                                        + (voting.find("label").text or "")
                                        + (voting.find("amendmentSubject").text or "")
                                    )
                                    doc = extract_doc(subject) or doc
                                    rcv = getattr(
                                        voting.find("rcv/value"), "text", None
                                    )
                                    split = extract_split(rcv or "")
                                    result = parse_result(voting.get("result"))
                                    if doc and result is not None:
                                        amendment = voting.find("amendmentNumber").text
                                        subject, amendment, type = parse_subject(
                                            subject or "", amendment
                                        )
                                        votes = voting.find("observations").text
                                        author = voting.find("amendmentAuthor").text
                                        sess_votes.append(
                                            dict(
                                                sess_date=sess_date,
                                                date=vote_date,
                                                doc=doc,
                                                subject=subject,
                                                author=(
                                                    json.dumps(parse_author(author))
                                                    if author
                                                    else None
                                                ),
                                                type=type,
                                                split=split,
                                                amendment=amendment,
                                                rcv=rcv is not None and "AN" in rcv,
                                                result=result,
                                                votes=(
                                                    json.dumps(
                                                        list(
                                                            map(int, votes.split(", "))
                                                        )
                                                    )
                                                    if votes
                                                    else None
                                                ),
                                                url=url,
                                            )
                                        )

                        url = f"{EP_BASE_URL}PV-{TERM}-{vote_date.strftime("%Y-%m-%d")}-RCV_FR.xml"
                        request = session.get(url)
                        try:
                            request.raise_for_status()
                        except requests.HTTPError:
                            continue
                        xml = ET.fromstring(request.content)
                        for entry in xml.findall("RollCallVote.Result"):
                            title = re.sub(
                                r"\s+",
                                " ",
                                "".join(
                                    entry.find(
                                        "RollCallVote.Description.Text"
                                    ).itertext()
                                ),
                            )
                            try:
                                doc = extract_doc(title)
                            except:
                                continue
                            match = re.search(r"am\s+(.*)", title.lower())
                            ref = extract_ref(title)
                            if match:
                                splits = match[1].split("/")

                                amendment = splits[0]

                                try:
                                    split = splits[1]
                                except:
                                    split = None
                            else:
                                amendment, split = None, None
                            subject, amendment, type = parse_subject(title, amendment)
                            id = entry.get("Identifier")
                            if id in processed:
                                continue
                            else:
                                processed.add(id)
                            if doc:
                                vote = dict(
                                    id=id,
                                    sess_date=sess_date,
                                    date=vote_date,
                                    subject=title,
                                    type=type,
                                    amendment=amendment,
                                    split=split,
                                    doc=doc,
                                    ref=ref,
                                    url=url.replace(".xml", ".html"),
                                )
                                positions = {}
                                votes = []
                                for position in ["For", "Against", "Abstention"]:
                                    groups = entry.find(f"Result.{position}")
                                    votes.append(
                                        int(groups.get("Number"))
                                        if groups is not None
                                        else 0
                                    )
                                    if groups is not None:
                                        for group in groups:
                                            for rcv in group:
                                                member_id = rcv.get(
                                                    "PersId", mepmap.get(rcv.text, None)
                                                )
                                                if (
                                                    member_id
                                                    and int(member_id)
                                                    in mepmap.values()
                                                ):
                                                    positions[member_id] = (
                                                        position.upper()
                                                    )
                                vote["positions"] = json.dumps(positions)
                                vote["votes"] = (
                                    json.dumps(votes) if len(votes) else None
                                )
                                sess_votings.append(vote)

                        url = f"{EP_BASE_URL}PV-{TERM}-{vote_date.strftime("%Y-%m-%d")}_FR.html"
                        pv = bs4.BeautifulSoup(
                            session.get(url).content, features="lxml"
                        )
                        for doc in set(
                            vote["doc"] for vote in sess_votes + sess_votings
                        ):
                            matches = pv.findAll(string=doc)
                            for match in matches:
                                try:
                                    lines = [
                                        p.text.lower()
                                        for p in match.find_parent(
                                            "p"
                                        ).find_next_siblings("p")
                                    ]
                                except:
                                    continue
                                for i, line in enumerate(lines):
                                    if "renvoi en commission" in line and not any(
                                        vote["doc"] == doc and vote["type"] == "RETURN"
                                        for vote in sess_votes + sess_votings
                                    ):
                                        result = (
                                            "ADOPTED"
                                            if "approuvé" in lines[i + 1]
                                            else "REJECTED"
                                        )
                                        sess_votes.append(
                                            dict(
                                                doc=doc,
                                                type="RETURN",
                                                url=url,
                                                date=vote_date,
                                                sess_date=sess_date,
                                                result=result,
                                            )
                                        )

                    import pandas as pd

                    votes_df = pd.DataFrame(sess_votes)
                    votings_df = pd.DataFrame(sess_votings)
                    if not votes_df.empty and not votings_df.empty:
                        votes_df = votes_df.query('type != "IGNORE"')
                        votings_df = votings_df.query('type != "IGNORE"')
                        if not votes_df.empty and not votings_df.empty:
                            on = [
                                "sess_date",
                                "doc",
                                "amendment",
                                "split",
                                "type",
                                "votes",
                            ]
                            try:
                                merged = votes_df.merge(
                                    votings_df,
                                    on=on,
                                    how="outer",
                                    suffixes=(None, "_rcv"),
                                    validate="1:1",
                                )
                            except pd.errors.MergeError:
                                print(
                                    votes_df[
                                        votes_df.duplicated(on, keep=False)
                                    ].values.tolist()
                                )
                                print(
                                    votings_df[
                                        votings_df.duplicated(on, keep=False)
                                    ].values.tolist()
                                )
                                exit()

                            merged = merged.replace(pd.NaT, None)
                            merged["date"] = merged.apply(
                                lambda row: row["date_rcv"] or row["date"], axis=1
                            )
                            merged = merged.drop(columns=["sess_date", "date_rcv"])
                            writer.writerows(merged.to_dict("records"))


if __name__ == "__main__":
    typer.run(main)
