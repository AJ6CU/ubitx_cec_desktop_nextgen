"""
The logbook: one QSO appended to an ADIF (.adi) or CSV file.

FIX (2026-11-10): LOG QSO WROTE NOTHING (Mark: "~/uBITX_Logbook.adi" never
changed) -- the new window's dialog was a mock-up whose Log button only
closed it. This is the old application's QSOLogger, without its Tk: that one
made a hidden tk.Tk() of its own -- a second Tk root inside this application
-- and showed its errors in message boxes. Here errors come back as text for
the dialog to show.

The file stays compatible with what the old application wrote, so an
existing logbook carries on: the same nine fields, in the same order
(QRZ's upload fields plus app_qrzlog_logid), the same ADIF header, a QSO
already in the log (same call, date, time and band) refused as a duplicate,
and a timestamped copy of the file made before a write -- at most once per
backup interval (minutes; 0 = before every write).
"""
import csv
import hashlib
import os
import shutil
from datetime import datetime

FIELDS = ("call", "band", "mode", "qso_date", "time_on", "freq", "rst_sent", "rst_rcvd", "app_id")
ADIF_HEADER = "ADIF Real-Time Log File Class\n<EOH>\n\n"

_last_backup = {}          # file -> when it was last copied


def adif_mode(rig_mode):
    """The ADIF mode for a rig mode: CWL/CWU are CW, LSB/USB are SSB."""
    mode = str(rig_mode or "").upper()
    if mode.startswith("CW"):
        return "CW"
    if mode in ("LSB", "USB"):
        return "SSB"
    return mode


def adif_band(name):
    """ "40 m" -> "40m", as ADIF writes bands."""
    return str(name or "").replace(" ", "").lower()


def _adif_field(record, name):
    """One field's value from an ADIF record (lower-cased text), or None."""
    marker = f"<{name}:"
    start = record.find(marker)
    if start < 0:
        return None
    end = record.find(">", start)
    if end < 0:
        return None
    spec = record[start + len(marker):end]
    try:
        length = int(spec.split(":")[0])        # <name:len> or <name:len:type>
    except ValueError:
        return None
    return record[end + 1:end + 1 + length].strip()


def _key(call, qso_date, time_on, band):
    return (str(call).upper().strip(), str(qso_date).strip(),
            str(time_on).strip(), str(band).lower().strip())


def _logged(path, is_adif):
    """The (call, date, time, band) of every QSO already in the file."""
    found = set()
    if not os.path.isfile(path):
        return found
    with open(path, "r", newline="", encoding="utf-8") as handle:
        if is_adif:
            for record in handle.read().lower().split("<eor>"):
                values = [_adif_field(record, f) for f in ("call", "qso_date", "time_on", "band")]
                if all(values):
                    found.add(_key(*values))
        else:
            for row in csv.DictReader(handle):
                found.add(_key(row.get("call", ""), row.get("qso_date", ""),
                               row.get("time_on", ""), row.get("band", "")))
    return found


def _backup(path, interval_minutes, now):
    """A timestamped copy of the file, unless one was made within the interval."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    last = _last_backup.get(path)
    if last is not None and (now - last).total_seconds() / 60.0 < float(interval_minutes or 0):
        return
    base, ext = os.path.splitext(path)
    shutil.copy2(path, f"{base}_backup_{now.strftime('%Y%m%d_%H%M%S')}{ext}")
    _last_backup[path] = now


def append_qso(path, qso, backup_minutes=0, now=None):
    """
    Appends one QSO to the logbook at path (.adi is ADIF, anything else CSV).
    qso holds call, band, mode, qso_date (YYYYMMDD), time_on (HHMM, UTC),
    freq (MHz), rst_sent, rst_rcvd. Returns (True, message) or (False, why).
    """
    now = now or datetime.now()
    missing = [f for f in FIELDS[:-1] if not str(qso.get(f, "")).strip()]
    if missing:
        return False, f"Missing: {', '.join(missing)}"
    record = {f: str(qso.get(f, "")).strip() for f in FIELDS[:-1]}
    record["call"] = record["call"].upper()
    record["band"] = record["band"].lower()
    is_adif = path.lower().endswith((".adi", ".adif"))
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        if _key(record["call"], record["qso_date"], record["time_on"], record["band"]) \
                in _logged(path, is_adif):
            return False, (f"{record['call']} on {record['band']} at {record['time_on']} "
                           "is already in the log.")
        _backup(path, backup_minutes, now)
        record["app_id"] = hashlib.md5(
            f"{record['call']}-{record['qso_date']}-{record['time_on']}-{record['band']}"
            .encode("utf-8")).hexdigest()[:12]
        exists = os.path.isfile(path) and os.path.getsize(path) > 0
        if is_adif:
            with open(path, "a" if exists else "w", encoding="utf-8") as handle:
                if not exists:
                    handle.write(ADIF_HEADER)
                row = ""
                for field in FIELDS:
                    value = record[field]
                    name = "app_qrzlog_logid" if field == "app_id" else field
                    row += f"<{name}:{len(value)}>{value} "
                handle.write(row + "<EOR>\n")
        else:
            with open(path, "a" if exists else "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                if not exists:
                    writer.writeheader()
                writer.writerow(record)
    except OSError as err:
        return False, f"Could not write {path}: {err}"
    return True, f"Logged {record['call']}."
