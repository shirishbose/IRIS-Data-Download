# -*- coding: utf-8 -*-
"""
Created on Mon May 25 10:48:19 2026

@author: Shirish Bose
"""

#!/usr/bin/env python3
import os
import csv
import requests
import time  # <-- Added to handle pacing/slowing down the script
from datetime import datetime, timedelta
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException

# ==========================================
# CONFIGURATION SETTINGS
# ==========================================
# Working Directory & Station File (in XC format)
WORK_DIR = "/home/shirish/SHIRISH/LgQTomography-main/DATA"
STATION_FILE = "AG1"

# Option to paste the station content (in XC format) directly in the code.
# If this list is populated, the script will use these inline stations instead of reading STATION_FILE.
# Set to an empty list [] to read from STATION_FILE.
# Example:
# INLINE_STATIONS = [
#     "XC|OR093|42.919399|-119.179802|1498.0|OR093|2007-08-20T00:00:00|2007-08-20T23:59:59"
# ]
INLINE_STATIONS = []

# ==========================================
# EVENT SOURCE
# ==========================================
USE_MANUAL_EVENT_FILE = True
EVENT_FILE = "event.txt"

# Option to paste manual event content directly in the code.
# If USE_MANUAL_EVENT_FILE is True and this list is populated, the script will use these inline events instead of reading EVENT_FILE.
# Example:
# INLINE_EVENTS = [
#     "2007-06-25, 05:30:00, 42.919399, -119.179802, 10.0, 0.0, 0.0, manual, 5.0"
# ]
INLINE_EVENTS = []
# ==========================================
# Web Service Clients
WAVEFORM_CLIENT = "IRIS"
ISC_EVENT_URL = "https://www.isc.ac.uk/fdsnws/event/1/query"
SEARCH_CHANNEL = "?HZ"
# SEARCH_CHANNEL = ["HH?", "BH?", "SH?"]

# Regional Event Search Parameters
MIN_MAG, MAX_MAG = 4.5, 10.0
MIN_DIST, MAX_DIST = 4, 22
MIN_DEP, MAX_DEP = 0.0, 80

# Waveform Extraction Window (seconds relative to origin time)
PRE_EVENT_SEC = 0
POST_EVENT_SEC = 800

# Rate Limiting Protection (Pacing in seconds)
SLEEP_SEC = 0  # <-- Pauses 4 seconds between requests (~15 requests per minute max)
# ==========================================

def parse_datetime(day_str, time_str):
    """Parses DD-MM-YYYY and HH:MM:SS into Obspy UTCDateTime."""
    dd, mm, yyyy = day_str.split("-")
    return UTCDateTime(f"{yyyy}-{mm}-{dd} {time_str}")

def get_isc_events(start_time, end_time, lat, lon):
    """Queries ISC for regional events and returns a parsed list of dictionaries."""
    s_date = start_time.strftime("%Y-%m-%d")
    e_date = end_time.strftime("%Y-%m-%d")

    # Avoid zero-length intervals for the web query
    if s_date == e_date:
        e_date = (datetime.strptime(e_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    params = {
        "starttime": s_date,
        "endtime": e_date,
        "minmagnitude": MIN_MAG,
        "maxmagnitude": MAX_MAG,
        "latitude": lat,
        "longitude": lon,
        "minradius": MIN_DIST,
        "maxradius": MAX_DIST,
        "mindepth": MIN_DEP,
        "maxdepth": MAX_DEP,
        "format": "text"
    }

    try:
        r = requests.get(ISC_EVENT_URL, params=params, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  [EVENT ERROR] Failed to fetch events from ISC: {e}")
        return []

    events = []
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("|")
        # Ensure the row has the required columns populated
        if len(cols) > 11 and all([cols[2], cols[3], cols[4], cols[10], cols[11]]):
            events.append({
                "time": UTCDateTime(cols[1]),
                "lat": float(cols[2]),
                "lon": float(cols[3]),
                "depth": float(cols[4]),
                "mag": float(cols[10]),
                "type": cols[9].lower()
            })
    return events

def parse_station_lines(lines):
    stations = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 8:
            continue
        net, sta, lat, lon, elev, desc, start_str, end_str = parts[:8]
        try:
            stations.append({
                "network": net,
                "station": sta,
                "starttime": UTCDateTime(start_str),
                "endtime": UTCDateTime(end_str),
                "latitude": float(lat),
                "longitude": float(lon)
            })
        except Exception as e:
            print(f"[SKIP] Bad station line: {line.strip()}")
            print(e)
    return stations

def parse_event_lines(lines):
    events = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        cols = [x.strip() for x in line.split(",")]
        try:
            # Check if cols[1] is a float (representing Latitude in unified-time format)
            # or if it is a time/date string (representing Time in split-time format)
            try:
                float(cols[1])
                is_unified_time = True
            except ValueError:
                is_unified_time = False

            if is_unified_time:
                ev_time = UTCDateTime(cols[0])
                lat = float(cols[1])
                lon = float(cols[2])
                depth = float(cols[3])
                mag = float(cols[4]) if len(cols) > 4 else 5.0
                ev_type = cols[5].lower() if len(cols) > 5 else "manual"
            else:
                ev_time = UTCDateTime(f"{cols[0]} {cols[1]}")
                lat = float(cols[2])
                lon = float(cols[3])
                depth = float(cols[4])
                mag = float(cols[8]) if len(cols) > 8 else 5.0
                ev_type = (cols[7].lower() if cols[7] else "manual") if len(cols) > 7 else "manual"
            
            events.append({
                "time": ev_time,
                "lat": lat,
                "lon": lon,
                "depth": depth,
                "mag": mag,
                "type": ev_type
            })
        except Exception as e:
            print(f"[SKIP] Bad event line: {line.strip()}")
            print(e)
    return events

def read_manual_events(event_file):
    try:
        with open(event_file, "r") as f:
            return parse_event_lines(f.readlines())
    except FileNotFoundError:
        print(f"  [ERROR] Event file '{event_file}' not found.")
        return []

def main():
    os.chdir(WORK_DIR)
    client = Client(WAVEFORM_CLIENT)

    # 1. Parse Station File
    stations = []
    if INLINE_STATIONS:
        print("  -> Using stations from INLINE_STATIONS configuration...")
        stations = parse_station_lines(INLINE_STATIONS)
    else:
        print(f"  -> Reading stations from {STATION_FILE}...")
        try:
            with open(STATION_FILE, "r") as f:
                stations = parse_station_lines(f.readlines())
        except FileNotFoundError:
            print(f"  [ERROR] Station file '{STATION_FILE}' not found. Please provide a valid file or use INLINE_STATIONS.")
            return

    # 2. Main Processing Loop
    for st in stations:
        print(f"\n{'='*60}\nProcessing Station: {st['network']}.{st['station']}\n{'='*60}")

        # --- STEP A: Fetch Events ---
        if USE_MANUAL_EVENT_FILE:
            if INLINE_EVENTS:
                print("  -> Using events from INLINE_EVENTS configuration...")
                events = parse_event_lines(INLINE_EVENTS)
            else:
                print(f"  -> Reading events from {EVENT_FILE}...")
                events = read_manual_events(EVENT_FILE)
            events = [ev for ev in events if st["starttime"] <= ev["time"] <= st["endtime"]]
            print(f"  -> Found {len(events)} events.")
        else:
            print("  -> Fetching regional events from ISC...")
            events = get_isc_events(st["starttime"], st["endtime"], st["latitude"], st["longitude"])
            # Be polite to the ISC event catalog server too
            time.sleep(2)

        if not events:
            print("  -> No events found for this station's operating window.")
            continue

        print(f"  -> Found {len(events)} events. Logging to CSV and fetching waveforms...")

        csv_file = f"{st['station']}.event.csv"
        with open(csv_file, "w", newline="") as out:
            writer = csv.writer(out)
            for ev in events:
                writer.writerow([ev["time"].strftime("%Y-%m-%d %H:%M:%S.%f"), ev["lat"], ev["lon"], f"{ev['depth']:.4f}", f"{ev['mag']:.1f}", ev["type"]])

        # --- STEP B: Download Waveforms & Write SAC ---
        for ev in events:
            ev_time = ev["time"]

            if not (st["starttime"] <= ev_time <= st["endtime"]):
                continue

            t1 = ev_time - PRE_EVENT_SEC
            t2 = ev_time + POST_EVENT_SEC

            try:
                st_data = client.get_waveforms(
                    network=st["network"],
                    station=st["station"],
                    location="*",
                    channel=SEARCH_CHANNEL,
                    starttime=t1,
                    endtime=t2
                )

                for tr in st_data:
                    tr.stats.sac = {}
                    tr.stats.sac.kstnm = st["station"]
                    tr.stats.sac.knetwk = st["network"]
                    tr.stats.sac.stla = st["latitude"]
                    tr.stats.sac.stlo = st["longitude"]
                    tr.stats.sac.evla = ev["lat"]
                    tr.stats.sac.evlo = ev["lon"]
                    tr.stats.sac.evdp = ev["depth"]
                    tr.stats.sac.mag = ev["mag"]
                    
                    tr.stats.sac.nzyear = ev_time.year
                    tr.stats.sac.nzjday = ev_time.julday
                    tr.stats.sac.nzhour = ev_time.hour
                    tr.stats.sac.nzmin = ev_time.minute
                    tr.stats.sac.nzsec = ev_time.second
                    tr.stats.sac.nzmsec = int(ev_time.microsecond / 1000)
                    
                    tr.stats.sac.b = -PRE_EVENT_SEC
                    tr.stats.sac.o = 0.0
                    tr.stats.sac.iztype = 11

                    sac_name = f"{ev_time.strftime('%Y%m%d%H%M%S')}.{tr.stats.station}.{tr.stats.channel}.SAC"
                    tr.write(sac_name, format="SAC")
                    print(f"  [SUCCESS] Saved: {sac_name}")

            except FDSNNoDataException:
                print(f"  [MISSING] No waveform data on server for {st['station']} at {ev_time}.")
            except Exception as e:
                print(f"  [ERROR] Waveform download failed for {ev_time}: {e}")
                if "429" in str(e) or "rate limiting" in str(e).lower():
                    print("  [ALERT] Hit rate limits! Cooling down for 15 seconds...")
                    time.sleep(15)
            
            # Pacing delay after every event attempt to prevent server overload
            time.sleep(SLEEP_SEC)

        # --- STEP C: Download RESP Files ---
        print(f"  -> Fetching RESP files for {st['station']}...")
        try:
            inventory = client.get_stations(
                network=st["network"],
                station=st["station"],
                location="*",
                channel=SEARCH_CHANNEL,
                starttime=st["starttime"],
                endtime=st["endtime"],
                level="channel"
            )
            time.sleep(SLEEP_SEC) # Delay after initial inventory pull

            found_channels = set()
            for net in inventory:
                for sta in net:
                    for chan in sta:
                        found_channels.add(chan.code)

            for ch_code in found_channels:
                resp_file = f"RESP.{st['network']}.{st['station']}.{ch_code}"
                
                if not os.path.exists(resp_file):
                    try:
                        client.get_stations(
                            network=st["network"],
                            station=st["station"],
                            location="*",
                            channel=ch_code,
                            starttime=st["starttime"],
                            endtime=st["endtime"],
                            level="response",
                            filename=resp_file
                        )
                        print(f"  [RESP SUCCESS] Downloaded: {resp_file}")
                    except Exception as e:
                        print(f"  [RESP ERROR] Could not get {ch_code}: {e}")
                        if "429" in str(e):
                            time.sleep(15)
                    
                    # Pacing delay between response file downloads
                    time.sleep(SLEEP_SEC)
                else:
                    print(f"  [RESP INFO] Already exists: {resp_file}")

        except Exception as e:
            print(f"  [RESP ERROR] Could not retrieve station inventory: {e}")

if __name__ == "__main__":
    main()
