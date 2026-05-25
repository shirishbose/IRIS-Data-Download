# -*- coding: utf-8 -*-
"""
Created on Mon May 25 10:48:19 2026

@author: Shirish Bose
"""

#!/usr/bin/env python3
import os
import csv
import requests
from datetime import datetime, timedelta
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException

# ==========================================
# CONFIGURATION SETTINGS
# ==========================================
# Working Directory & Station File
WORK_DIR = r"D:\YL_SPLIT"
STATION_FILE = "YL"

# Web Service Clients
WAVEFORM_CLIENT = "IRIS"
ISC_EVENT_URL = "https://www.isc.ac.uk/fdsnws/event/1/query"
SEARCH_CHANNEL = "BH?"

# Regional Event Search Parameters
MIN_MAG, MAX_MAG = 5.5, 10.0
MIN_DIST, MAX_DIST = 80, 135
MIN_DEP, MAX_DEP = 0.0, 10000

# Waveform Extraction Window (seconds relative to origin time)
PRE_EVENT_SEC = 0
POST_EVENT_SEC = 2000
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

def main():
    os.chdir(WORK_DIR)
    client = Client(WAVEFORM_CLIENT)

    # 1. Parse Station File
    stations = []
    with open(STATION_FILE, "r") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 8:
                continue
            
            net, sta, start_d, start_t, end_d, end_t, lat, lon = parts[:8]
            stations.append({
                "network": net,
                "station": sta,
                "starttime": parse_datetime(start_d, start_t),
                "endtime": parse_datetime(end_d, end_t),
                "latitude": float(lat),
                "longitude": float(lon)
            })

    # 2. Main Processing Loop
    for st in stations:
        print(f"\n{'='*60}\nProcessing Station: {st['network']}.{st['station']}\n{'='*60}")

        # --- STEP A: Fetch Events ---
        print("  -> Fetching regional events from ISC...")
        events = get_isc_events(st["starttime"], st["endtime"], st["latitude"], st["longitude"])

        if not events:
            print("  -> No events found for this station's operating window.")
            continue

        print(f"  -> Found {len(events)} events. Logging to CSV and fetching waveforms...")

        # Keep a CSV record (optional, but good for archiving)
        csv_file = f"{st['station']}.event.csv"
        with open(csv_file, "w", newline="") as out:
            writer = csv.writer(out)
            for ev in events:
                writer.writerow([ev["time"].strftime("%Y-%m-%d %H:%M:%S.%f"), ev["lat"], ev["lon"], f"{ev['depth']:.4f}", f"{ev['mag']:.1f}", ev["type"]])

        # --- STEP B: Download Waveforms & Write SAC ---
        for ev in events:
            ev_time = ev["time"]

            # Double-check strict station uptime limits
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
                    # Initialize and assign SAC headers
                    tr.stats.sac = {}
                    tr.stats.sac.kstnm = st["station"]
                    tr.stats.sac.knetwk = st["network"]
                    tr.stats.sac.stla = st["latitude"]
                    tr.stats.sac.stlo = st["longitude"]
                    tr.stats.sac.evla = ev["lat"]
                    tr.stats.sac.evlo = ev["lon"]
                    tr.stats.sac.evdp = ev["depth"]
                    tr.stats.sac.mag = ev["mag"]
                    
                    # Exact reference time assignment
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
                else:
                    print(f"  [RESP INFO] Already exists: {resp_file}")

        except Exception as e:
            print(f"  [RESP ERROR] Could not retrieve station inventory: {e}")

if __name__ == "__main__":
    main()