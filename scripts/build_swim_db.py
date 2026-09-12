#!/usr/bin/env python3
"""
Build results/swim_history.db from the raw text/HTML/CSV extracts under
results/history/ and results/all_city_2026_results.csv.

Produces one `swimmers` table:
  id, decade, year, first_name, last_name, full_name_raw, age, team, event,
  prelim_time, final_time, place, points, source_file, confidence

Run: python3 scripts/build_swim_db.py
"""
import csv
import glob
import os
import re
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(REPO, "results", "history")
DB_PATH = os.path.join(REPO, "results", "swim_history.db")

TIME_RE = r'(?:\d{1,2}:)?\d{1,3}\.\d{2}'
TIME_TOKEN_RE = re.compile(TIME_RE)

rows = []  # list of dicts, one per swimmer result


def add_row(decade, year, first_name, last_name, full_name_raw, age, team,
            event, prelim_time, final_time, place, points, source_file,
            confidence):
    rows.append(dict(
        decade=decade, year=year, first_name=first_name, last_name=last_name,
        full_name_raw=full_name_raw, age=age, team=team, event=event,
        prelim_time=prelim_time, final_time=final_time, place=place,
        points=points, source_file=source_file, confidence=confidence,
    ))


def split_last_first(last, first):
    last = re.sub(r'\s+', ' ', last).strip().strip(',')
    first = re.sub(r'\s+', ' ', first).strip()
    return first, last, f"{last}, {first}"


def clean_num(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Era A: HY-TEK "modern" report format used 2000-2009, 2010-2019, 2021-2025
#   Event header:  "Event N  Girls/Boys AGE-GROUP DISTANCE STROKE"
#   Column header: "Name ... Age Team ... Prelims  Finals [Points]"
#                  or "Team ... Seed  Finals [Points]" (relay -> skip, no name)
#   Row:  RANK  Last, First   AGE  TEAM   [PRELIM]  FINAL  [POINTS]
# ---------------------------------------------------------------------------
EVENT_HDR_RE = re.compile(r'^\s*Event\s*(\d+)\s+(.*\S)\s*$')
HEADER_ROW_RE = re.compile(r'^(PL\s+)?Name\b.*\bTeam\b')
ROW_RE_A = re.compile(
    r'^\s*(?P<rank>\d+|--|\*)?\s*'
    r'(?P<last>[A-Za-z][A-Za-z\'\.\- ]*?),\s+'
    r'(?P<first>[A-Za-z][A-Za-z\'\.\- ]*?)\s+'
    r'(?P<age>\d{1,2})\s+'
    r'(?P<team>[A-Za-z][A-Za-z\'\.\-&/ ]*?)\s+'
    r'(?P<rest>(?:\d|DQ|NS|SCR|--).*)$'
)
# 2007-2009 (and some 2003-2004) individual rows use "First Last" with no
# comma, instead of "Last, First" -- try this if ROW_RE_A doesn't match.
ROW_RE_A_NOCOMMA = re.compile(
    r'^\s*(?P<rank>\d+|--|\*)?\s*'
    r'(?P<first>[A-Z][a-zA-Z\'\.\-]+)\s+'
    r'(?P<last>[A-Z][a-zA-Z\'\.\-]+)\s+'
    r'(?P<age>\d{1,2})\s+'
    r'(?P<team>[A-Za-z][A-Za-z\'\.\-&/ ]*?)\s+'
    r'(?P<rest>(?:\d|DQ|NS|SCR|--).*)$'
)


def parse_rest_tokens(rest, has_prelim_col, in_prelim_section):
    """Return (prelim_time, final_time, place_points) from the trailing part
    of a result row, after the team field."""
    times = TIME_TOKEN_RE.findall(rest)
    # points = a bare small integer token at the very end, not part of a time
    points = None
    tail = rest.strip()
    m = re.search(r'(\d{1,4})\s*$', tail)
    if m:
        # only treat as points if it's not actually the tail of the last time token
        end = m.end()
        start = m.start()
        # if immediately preceded by '.' it's part of a decimal time -> not points
        if start == 0 or tail[start - 1] != '.':
            points = clean_num(m.group(1))

    if len(times) >= 2:
        return times[0], times[1], points
    if len(times) == 1:
        if has_prelim_col and in_prelim_section:
            return times[0], None, points
        return None, times[0], points
    return None, None, points


def parse_hytek_modern(text, decade, source_label, default_year=None):
    """HY-TEK complete_results/age-group pages repeat some individual events
    twice: once as the authoritative Results table (Prelims+Finals+Points,
    "Championship"/"Consolation"/"A - Final"/etc. sections) and again right
    after as a plain Seed/Prelims heat-sheet listing for the *same* event --
    but that second listing isn't purely redundant: it also includes extra
    entrants who swam prelims but didn't final, who appear nowhere else. So
    rather than discard the repeat outright, buffer rows per event keyed by
    swimmer name: a name repeated in the second block just fills in gaps
    (never overwrites the authoritative final/place/points), while a name
    seen only in the second block is kept as a prelim-only addition.
    """
    lines = text.split('\n')
    current_year = default_year
    current_event = None
    has_prelim_col = False
    in_prelim_section = False
    n = [0]
    buf = {}  # full_name_raw -> row dict, for the currently open event

    def flush():
        for row in buf.values():
            add_row(decade, current_year, row['first'], row['last'],
                    row['full_raw'], row['age'], row['team'], row['event'],
                    row['prelim'], row['final'], row['place'], row['points'],
                    source_label, 'high')
            n[0] += 1
        buf.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        ym = re.match(r'^File:\s*(\d{4})', stripped)
        if ym:
            flush()
            current_year = int(ym.group(1))
            current_event = None
            continue
        if not stripped:
            continue
        hdr = EVENT_HDR_RE.match(stripped)
        if hdr:
            norm = re.sub(r'\s+', ' ', stripped).strip()
            if norm != current_event:
                flush()
                current_event = norm
            has_prelim_col = False
            in_prelim_section = False
            continue
        if HEADER_ROW_RE.match(stripped):
            has_prelim_col = 'Prelim' in stripped
            in_prelim_section = False
            continue
        if stripped.startswith('Team') and 'Seed' in stripped:
            # relay column header; individual rows won't match ROW_RE_A anyway
            continue
        low = stripped.lstrip('*').strip().lower()
        if low in ('preliminaries', 'preliminary'):
            in_prelim_section = True
            continue
        if low in ('championship', 'consolation', 'consolations', 'bonus',
                   'a - final', 'b - final', 'c - final', 'timed finals'):
            in_prelim_section = False
            continue

        m = ROW_RE_A.match(line) or ROW_RE_A_NOCOMMA.match(line)
        if not m or current_event is None:
            continue
        first, last, full_raw = split_last_first(m.group('last'), m.group('first'))
        age = clean_num(m.group('age'))
        team = re.sub(r'\s+', ' ', m.group('team')).strip()
        prelim, final, points = parse_rest_tokens(
            m.group('rest'), has_prelim_col, in_prelim_section)
        rank_raw = m.group('rank')
        place = clean_num(rank_raw) if rank_raw and rank_raw.isdigit() else None

        existing = buf.get(full_raw)
        if existing:
            if existing['prelim'] is None and prelim is not None:
                existing['prelim'] = prelim
            if existing['final'] is None and final is not None:
                existing['final'] = final
            if existing['place'] is None and place is not None:
                existing['place'] = place
            if existing['points'] is None and points is not None:
                existing['points'] = points
        else:
            buf[full_raw] = dict(first=first, last=last, full_raw=full_raw,
                                  age=age, team=team, event=current_event,
                                  prelim=prelim, final=final, place=place,
                                  points=points)
    flush()
    return n[0]


# ---------------------------------------------------------------------------
# Era B: 1990s HTML report format (1991, 1995-1999)
#   "File: 1991/8ugirls.htm (8 & Under Girls)"
#   "Event N  Girls/Boys AGE  DISTANCE Stroke"
#   optional "Prelim  Final" column header
#   Row: "N. First Last     TEAMCODE   [PRELIM]   FINAL"
# ---------------------------------------------------------------------------
FILE_HDR_1990S_RE = re.compile(
    r'^File:\s*(\d{4})/([\w\.\-]+)(?:\s*\(([^)]*)\))?')
ROW_RE_B = re.compile(
    r'^\s*(?P<rank>\d+)\.\s+'
    r'(?P<name>[A-Za-z][A-Za-z\'\.\- ]*?)\s+'
    r'(?P<team>[A-Za-z]{2,4})\s+'
    r'(?P<t1>' + TIME_RE + r'|DQ|NS)'
    r'(?:\s+(?P<t2>' + TIME_RE + r'))?\s*$'
)


def parse_hytek_1990s_html(text, source_label):
    lines = text.split('\n')
    current_year = None
    current_event = None
    current_age_group = None
    has_prelim_col = False
    in_prelim_section = False
    n = 0
    for raw in lines:
        stripped = raw.strip()
        fh = FILE_HDR_1990S_RE.match(stripped)
        if fh:
            current_year = int(fh.group(1))
            current_age_group = fh.group(3)
            current_event = None
            has_prelim_col = False
            in_prelim_section = False
            continue
        if not stripped:
            continue
        hdr = EVENT_HDR_RE.match(stripped)
        if hdr:
            current_event = re.sub(r'\s+', ' ', stripped).strip()
            has_prelim_col = False
            in_prelim_section = False
            continue
        if 'prelim' in stripped.lower() and 'final' in stripped.lower():
            has_prelim_col = True
            continue
        if stripped.lower() == 'preliminaries':
            in_prelim_section = True
            continue

        m = ROW_RE_B.match(stripped)
        if not m:
            continue
        event = current_event or current_age_group
        if event is None:
            continue
        name = re.sub(r'\s+', ' ', m.group('name')).strip()
        parts = name.split(' ')
        if len(parts) < 2:
            continue
        first = ' '.join(parts[:-1])
        last = parts[-1]
        full_raw = f"{last}, {first}"
        team = m.group('team')
        t1, t2 = m.group('t1'), m.group('t2')
        if t1 in ('DQ', 'NS'):
            prelim, final = None, None
        elif t2:
            prelim, final = t1, t2
        elif has_prelim_col and in_prelim_section:
            prelim, final = t1, None
        else:
            prelim, final = None, t1
        add_row('1990s', current_year, first, last, full_raw, None, team,
                event, prelim, final, None, None, source_label, 'high')
        n += 1
    return n


# ---------------------------------------------------------------------------
# Era C: 1992-1994 "Full Meet Results" OCR'd PDFs (all-caps, ID-numbered)
#   "Girls Event 1 100 R-Medley 8 & Under" / "Boys Event20 100 Free 15-18"
#   Row: "3 1372 BAUCH, ERIK 16 MI 50.31"  (rank, id, LAST, FIRST, age, team, time)
# ---------------------------------------------------------------------------
EVENT_HDR_C_RE = re.compile(
    r'(?:^|:\s*)(?:\S+\s+)?Event\s*(\d+)\s+([0-9A-Za-z&\-\s]*?)(?=\s*:|\s*$)')
# Not anchored to line start/end: 1993/1994 OCR often concatenates two
# side-by-side report columns onto one physical text line, sometimes with a
# ' : ' column-rule artifact between them and sometimes with none at all.
# Rather than try to reliably split columns (the separator is inconsistent),
# we scan each line for every embedded result row, in order.
ROW_RE_C = re.compile(
    r'(?P<rank>\d{1,2}|-|\*)?\s*(?P<id>\d{2,6})\s+'
    r'(?P<last>[A-Z][A-Za-z\'\.\- ]*?),\s*'
    r'(?P<first>[A-Z][A-Za-z\'\.\- ]*?)\s+'
    r'(?P<age>\d{1,2})\s+'
    r'(?P<team>[A-Za-z]{2,4})\s+'
    r'(?P<time>[\dOSs§]{1,2}(?:[:.][\dOSs§]{2}){1,2})'
)


def ocr_fix_time(t):
    t = t.replace('S', '5').replace('s', '5').replace('§', '5').replace('O', '0')
    # normalize the rare "1.06.14" (both separators OCR'd as '.') -> "1:06.14"
    parts = re.split(r'[:.]', t)
    if len(parts) == 3:
        return f"{parts[0]}:{parts[1]}.{parts[2]}"
    return t


def parse_1990s_full_meet_pdf(text, year, source_label):
    lines = text.split('\n')
    current_event = None
    in_prelim_section = False
    n = [0]
    # Buffer rows per (event) so a swimmer's "Championship/Consolation"
    # final-time row and their redundant "Preliminaries" prelim-time row
    # (same event, same swimmer, same underlying meet -- these HY-TEK-era
    # reports list both) merge into a single result instead of two rows.
    buf = {}  # full_name_raw -> row dict, for the currently open event

    def flush():
        for row in buf.values():
            add_row('1990s', year, row['first'], row['last'], row['full_raw'],
                    row['age'], row['team'], row['event'], row['prelim'],
                    row['final'], row['place'], None, source_label, 'medium')
            n[0] += 1
        buf.clear()

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        headers = list(EVENT_HDR_C_RE.finditer(stripped))
        if headers:
            flush()
            # last header wins when a line straddles two report columns
            h = headers[-1]
            current_event = f"Event {h.group(1)} {h.group(2).strip()}"
            in_prelim_section = False
        low = stripped.lower()
        if low.startswith('prelimin'):
            in_prelim_section = True
            continue
        if low in ('championship', 'consolations', 'consolation', 'finals'):
            in_prelim_section = False
            continue
        if current_event is None:
            continue
        for m in ROW_RE_C.finditer(stripped):
            first, last, full_raw = split_last_first(m.group('last'), m.group('first'))
            age = clean_num(m.group('age'))
            team = m.group('team')
            time_val = ocr_fix_time(m.group('time'))
            rank_raw = m.group('rank')
            place = clean_num(rank_raw) if rank_raw and rank_raw.isdigit() else None
            existing = buf.get(full_raw)
            if in_prelim_section:
                if existing:
                    existing['prelim'] = time_val
                else:
                    buf[full_raw] = dict(first=first, last=last, full_raw=full_raw,
                                          age=age, team=team, event=current_event,
                                          prelim=time_val, final=None, place=None)
            else:
                if existing:
                    existing['final'] = time_val
                    existing['place'] = place
                    existing['age'] = age
                    existing['team'] = team
                else:
                    buf[full_raw] = dict(first=first, last=last, full_raw=full_raw,
                                          age=age, team=team, event=current_event,
                                          prelim=None, final=time_val, place=place)
    flush()
    return n[0]


# ---------------------------------------------------------------------------
# Era D: 1990 OCR results + 1970s/1980s scanned OCR PDFs -- low confidence
#   best-effort (surname, team) proximity extraction; age/event/time left NULL
#   unless a nearby age-group/event header can be reasonably associated.
# ---------------------------------------------------------------------------
# Teams that actually existed in the league during the 1970s/1980s/1990
# OCR-covered years -- deliberately excludes Seminole, High Point, Hawks
# Landing, Goodman, etc. (all much later additions), since including them
# here would cause false-positive (surname, team) matches against unrelated
# capitalized words in this noisy OCR text.
TEAM_FULLNAMES = [
    'Shorewood Hills', 'Shorewood', 'Ridgewood', 'Hill Farm', 'West Side',
    'Westside', 'Parkcrest', 'Monona', 'Nakoma', 'Maple Bluff', 'Middleton',
    'Cherokee',
]
TEAM_CODE_RE = re.compile(r'\b([A-Z]{2,4})\b[.,]?\s*$')
NAME_CODE_RE = re.compile(
    r'^[\W\d]{0,6}'
    r'(?P<name>[A-Z][a-zA-Z\'\.]+(?:[,]?\s+[A-Z][a-zA-Z\'\.]*){1,3})'
    r'[.,]?\s+'
    r'(?P<team>[A-Z]{2,4})[.,]?\s*$'
)
TEAM_FULLNAME_RE = re.compile(
    r'(?P<name>[A-Z][a-zA-Z\'\.]+(?:[,]?\s+[A-Z][a-zA-Z\'\.]*){0,2})\s+'
    r'(?P<team>' + '|'.join(re.escape(t) for t in TEAM_FULLNAMES) + r')\b',
)
LOW_CONF_EVENT_HDR_RE = re.compile(
    r'^\s*(Girls?|Boys?)\b.{0,60}\b(Free|Back|Breast|Fly|Medley|I\.?M\.?|Relay)\b',
    re.IGNORECASE,
)
KNOWN_CODES = {
    'SW', 'RW', 'HF', 'WS', 'PC', 'MO', 'NK', 'MB', 'MI', 'CH', 'SE', 'HP',
    'HL', 'GW', 'SEM', 'MID', 'HFSC', 'WSSC',
}


def guess_first_last(name):
    name = re.sub(r'\s+', ' ', name).strip().strip(',')
    if ',' in name:
        last, first = name.split(',', 1)
        return first.strip(), last.strip()
    parts = name.split(' ')
    if len(parts) == 1:
        return None, parts[0]
    return ' '.join(parts[:-1]), parts[-1]


def parse_low_confidence_ocr(text, decade, year, source_label):
    lines = text.split('\n')
    current_event = None
    year_local = year
    skip_file = False
    n = 0
    with_event = 0
    for raw in lines:
        stripped = raw.strip()
        fh = re.match(r'^File:\s*(\S+)', stripped)
        if fh:
            # "Swim News" files are newspaper-clipping prose, not results
            # tables -- skip them, they only add false-positive name/team
            # matches against unrelated capitalized words in running text.
            skip_file = 'news' in fh.group(1).lower()
            ym = re.search(r'(\d{4})', fh.group(1))
            if ym:
                year_local = int(ym.group(1))
            current_event = None
            continue
        if skip_file:
            continue
        if not stripped:
            continue
        if 'rec.' in stripped.lower() or stripped.lower().startswith('record'):
            continue
        if (LOW_CONF_EVENT_HDR_RE.match(stripped) and len(stripped) < 90
                and 'rec' not in stripped.lower()):
            current_event = re.sub(r'\s+', ' ', stripped)
            continue

        m = NAME_CODE_RE.match(stripped) or None
        cand = None
        if m and m.group('team') in KNOWN_CODES:
            cand = (m.group('name'), m.group('team'))
        else:
            fm = TEAM_FULLNAME_RE.search(stripped)
            if fm:
                cand = (fm.group('name'), fm.group('team'))
        if not cand:
            continue
        name, team = cand
        first, last = guess_first_last(name)
        if not last or len(last) < 2:
            continue
        full_raw = f"{last}, {first}" if first else last
        yr = year_local if year_local else year
        add_row(decade, yr, first, last, full_raw, None, team,
                current_event, None, None, None, None, source_label, 'low')
        n += 1
        if current_event:
            with_event += 1
    return n, with_event


# ---------------------------------------------------------------------------
# Era E: 2026 structured CSV
# ---------------------------------------------------------------------------
def parse_2026_csv(path):
    n = 0
    groups = {}
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            ev = row['Event Name'].strip()
            round_ = None
            base = ev
            if ev.endswith('Prelims'):
                round_ = 'prelim'
                base = ev[:-len('Prelims')].strip()
            elif ev.endswith('Finals'):
                round_ = 'final'
                base = ev[:-len('Finals')].strip()
            swimmer = row['Swimmer'].strip()
            team = row['Team'].strip()
            age = clean_num(row['Age'])
            key = (base, swimmer, team, age)
            g = groups.setdefault(key, {'prelim': None, 'final': None,
                                         'place': None, 'points': None})
            t = row['Finals Time'].strip() or None
            if round_ == 'prelim':
                g['prelim'] = t
            else:
                g['final'] = t
                if row['Place'].strip():
                    g['place'] = clean_num(row['Place'])
                if row['Points'].strip():
                    g['points'] = clean_num(row['Points'])
                if round_ is None:
                    # relay "Timed Finals" rows: only one round exists
                    if row['Place'].strip():
                        g['place'] = clean_num(row['Place'])
    for (base, swimmer, team, age), g in groups.items():
        if ',' in swimmer:
            last, first = swimmer.split(',', 1)
            first, last = first.strip(), last.strip()
        else:
            first, last = guess_first_last(swimmer)
        full_raw = f"{last}, {first}" if first else last
        add_row('2020s', 2026, first, last, full_raw, age, team, base,
                g['prelim'], g['final'], g['place'], g['points'],
                'all_city_2026_results.csv', 'high')
        n += 1
    return n


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def read(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def main():
    total = 0

    # 2000-2009, 2010-2019, 2021-2025 -- modern HY-TEK format
    modern_sources = [
        ('2000s', os.path.join(HISTORY, '2000-2009', 'All_City_Swim_Results_2000-2009.txt')),
        ('2010s', os.path.join(HISTORY, '2010s', 'All_City_Swim_Results_2010-2019.txt')),
        ('2020s', os.path.join(HISTORY, '2021-2025', 'All_City_Swim_Complete_Results_2021-2025.txt')),
    ]
    for decade, path in modern_sources:
        text = read(path)
        cnt = parse_hytek_modern(text, decade, os.path.relpath(path, REPO))
        print(f"{decade} ({os.path.basename(path)}): {cnt} rows")
        total += cnt

    # 1990s: 1990 OCR (low), 1991 + 1995-1999 HTML (high), 1992-1994 OCR PDF (medium)
    path_1990s = os.path.join(HISTORY, '1990-1999', '1990-1999_Swim_Text_Extract.txt')
    text_1990s = read(path_1990s)
    src_1990s = os.path.relpath(path_1990s, REPO)

    # split out the 1990 OCR block (before the first "File: swim-1991" marker)
    split_idx = text_1990s.find('\nFile: swim-1991')
    block_1990_ocr = text_1990s[:split_idx] if split_idx != -1 else ''
    rest_1990s = text_1990s[split_idx:] if split_idx != -1 else text_1990s

    n_low, with_event = parse_low_confidence_ocr(block_1990_ocr, '1990s', 1990, src_1990s)
    print(f"1990 OCR: {n_low} rows (low confidence)")
    total += n_low

    # pull out each 1992/1993/1994 full-meet-results OCR sub-block, and split
    # the remaining HTML pages into the 1991-style report (no age/comma; see
    # parse_hytek_1990s_html) vs. the 1995-1999-style report, which already
    # matches the "modern" HY-TEK Last,First/Age/Team/Prelims/Finals layout
    # used from 2000 onward (right down to repeating a redundant Seed/Prelims
    # block per event -- parse_hytek_modern()'s per-event row buffering
    # handles that here too).
    file_blocks = re.split(r'(?=^File: )', rest_1990s, flags=re.M)
    html_1991_accum = []
    html_modern_accum = []
    for blk in file_blocks:
        fm = re.match(r'^File:\s*(\S+)', blk)
        if not fm:
            continue
        fname = fm.group(1)
        ym = re.search(r'(199[234])_Full_Meet_Results\.pdf', fname)
        if ym:
            year = int(ym.group(1))
            cnt = parse_1990s_full_meet_pdf(blk, year, src_1990s)
            print(f"{year} Full Meet Results PDF: {cnt} rows (medium confidence)")
            total += cnt
            continue
        yfm = re.match(r'^(\d{4})/', fname)
        if yfm and yfm.group(1) == '1991':
            html_1991_accum.append(blk)
        else:
            html_modern_accum.append(blk)

    html_1991_text = '\n'.join(html_1991_accum)
    cnt = parse_hytek_1990s_html(html_1991_text, src_1990s)
    print(f"1991 HTML: {cnt} rows")
    total += cnt

    html_modern_text = '\n'.join(html_modern_accum)
    cnt = parse_hytek_modern(html_modern_text, '1990s', src_1990s)
    print(f"1995-1999 HTML: {cnt} rows")
    total += cnt

    # 1970s / 1980s scanned OCR -- low confidence
    low_conf_sources = []
    for y in range(1972, 1980):
        d = os.path.join(HISTORY, str(y))
        if os.path.isdir(d):
            for fp in sorted(glob.glob(os.path.join(d, '*.txt'))):
                low_conf_sources.append(('1970s', y, fp))
    path_1980s = os.path.join(HISTORY, '1980s', '1980s_Swim_PDF_Text_Extracts.txt')
    if os.path.exists(path_1980s):
        low_conf_sources.append(('1980s', None, path_1980s))

    total_low = 0
    total_low_with_event = 0
    for decade, year, path in low_conf_sources:
        text = read(path)
        src = os.path.relpath(path, REPO)
        cnt, with_event = parse_low_confidence_ocr(text, decade, year, src)
        total_low += cnt
        total_low_with_event += with_event
    print(f"1970s/1980s OCR: {total_low} rows (low confidence), "
          f"{total_low_with_event} with event context, "
          f"{total_low - total_low_with_event} without")
    total += total_low

    # 2026 CSV
    csv_path = os.path.join(REPO, 'results', 'all_city_2026_results.csv')
    cnt = parse_2026_csv(csv_path)
    print(f"2026 CSV: {cnt} rows")
    total += cnt

    print(f"\nTotal rows parsed (pre-dedup): {total}")

    # ---- write to sqlite, deduping exact repeats ----
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE swimmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decade TEXT,
            year INTEGER,
            first_name TEXT,
            last_name TEXT,
            full_name_raw TEXT,
            age INTEGER,
            team TEXT,
            event TEXT,
            prelim_time TEXT,
            final_time TEXT,
            place INTEGER,
            points INTEGER,
            source_file TEXT,
            confidence TEXT
        )
    ''')

    seen = set()
    inserted = 0
    duplicates = 0
    for r in rows:
        key = (r['decade'], r['year'], r['full_name_raw'], r['event'], r['final_time'])
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        conn.execute(
            'INSERT INTO swimmers (decade, year, first_name, last_name, '
            'full_name_raw, age, team, event, prelim_time, final_time, '
            'place, points, source_file, confidence) VALUES '
            '(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (r['decade'], r['year'], r['first_name'], r['last_name'],
             r['full_name_raw'], r['age'], r['team'], r['event'],
             r['prelim_time'], r['final_time'], r['place'], r['points'],
             r['source_file'], r['confidence']))
        inserted += 1

    conn.execute('CREATE INDEX idx_swimmers_name ON swimmers(last_name, first_name)')
    conn.execute('CREATE INDEX idx_swimmers_decade_year ON swimmers(decade, year)')
    conn.commit()
    print(f"Inserted {inserted} rows, collapsed {duplicates} exact duplicates.")
    conn.close()


if __name__ == '__main__':
    sys.exit(main())
