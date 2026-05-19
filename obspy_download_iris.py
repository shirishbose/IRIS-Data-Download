#!/usr/bin/env python3
import os
import pandas as pd
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
# Optional: Import specific exception for cleaner error handling
from obspy.clients.fdsn.header import FDSNNoDataException

# -----------------------------
# User settings
# -----------------------------
os.chdir("/home/shirish/SHIRISH/IRIS_Download/XL")
xr_file = "XL"  # Station info
client = Client("IRIS")

#  <--- Variable for Channel (Change to "HH?" or "EH?" if needed) --->
search_channel = "HH?" 
# ---------------------------------------------------------------------------

# -----------------------------
# Helper to parse DD-MM-YYYY to UTCDateTime
# -----------------------------
def parse_datetime(day_str, time_str):
    dd, mm, yyyy = day_str.split("-")
    dt_str = f"{yyyy}-{mm}-{dd} {time_str}"
    return UTCDateTime(dt_str)

# -----------------------------
# Read XR station file
# -----------------------------
stations = []
with open(xr_file, "r") as f:
    for line in f:
        parts = line.split()
        if len(parts) < 8: continue 
        net, sta, start_d, start_t, end_d, end_t, lat, lon = parts[:8]
        
        starttime = parse_datetime(start_d, start_t)
        endtime   = parse_datetime(end_d, end_t)
        stations.append({
            "network": net,
            "station": sta,
            "starttime": starttime,
            "endtime": endtime,
            "latitude": float(lat),
            "longitude": float(lon)
        })

# -----------------------------
# Loop over stations
# -----------------------------
for st in stations:
    print(f"Processing Station: {st['station']}")
    
    # --- Part 1: Download Waveforms (Events) ---
    event_file = f"{st['station']}.event.csv"
    if os.path.exists(event_file):
        df = pd.read_csv(event_file, header=None)
        df.columns = ["time", "lat", "lon", "depth", "mag", "type"]

        for i, row in df.iterrows():
            ev_time = UTCDateTime(row["time"])
            
            # Skip if event is outside station operation time
            if not (st["starttime"] <= ev_time <= st["endtime"]):
                print(f"  Skipping event {ev_time}: Outside station uptime.")
                continue

            # Request window
            b = 300; e = 3000
            t1 = ev_time - b
            t2 = ev_time + e

            try:
                st_data = client.get_waveforms(
                    network=st["network"],
                    station=st["station"],
                    location="*",
                    channel=search_channel,
                    starttime=t1, endtime=t2
                )

                # Update SAC headers and save
                for tr in st_data:
                    tr.stats.sac = {}
                    tr.stats.sac.kstnm = st["station"]
                    tr.stats.sac.knetwk = st["network"]
                    tr.stats.sac.stla = st["latitude"]
                    tr.stats.sac.stlo = st["longitude"]
                    tr.stats.sac.evla = row["lat"]
                    tr.stats.sac.evlo = row["lon"]
                    tr.stats.sac.evdp = row["depth"]
                    tr.stats.sac.mag = row["mag"]
                    tr.stats.sac.o = 0
                    
                    # Set the reference time exactly to ev_time
                    tr.stats.sac.nzyear = ev_time.year
                    tr.stats.sac.nzjday = ev_time.julday
                    tr.stats.sac.nzhour = ev_time.hour
                    tr.stats.sac.nzmin = ev_time.minute
                    tr.stats.sac.nzsec = ev_time.second
                    tr.stats.sac.nzmsec = int(ev_time.microsecond / 1000)
                    tr.stats.sac.b = -b
                    tr.stats.sac.o = 0.0
                    tr.stats.sac.iztype = 11
                    # ----------------------------------------------------
                    sac_name = f"{ev_time.strftime('%Y%m%d%H%M%S')}.{tr.stats.station}.{tr.stats.channel}.SAC"
                    tr.write(sac_name, format="SAC")
                    print(f"  [SUCCESS] Saved: {sac_name}")

            # --- MODIFICATION START: Explicitly print if data not found ---
            except FDSNNoDataException:
                print(f"  [MISSING] No data on server for {st['station']} at {ev_time}.")
            except Exception as e:
                print(f"  [ERROR] Failed to download {st['station']} at {ev_time}: {e}")
            # --- MODIFICATION END ---

    else:
        print(f"  Event file {event_file} not found.")

    # --- Part 2: Download RESP files ---
    try:
        inventory = client.get_stations(
            network=st["network"],
            station=st["station"],
            location="*",
            channel=search_channel, 
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
                    print(f"  [RESP] Downloaded: {resp_file}")
                except Exception as e:
                    print(f"  [RESP ERROR] Could not get {ch_code}: {e}")
            else:
                 print(f"  [RESP] Exists: {resp_file}")

    except Exception as e:
        print(f"  [RESP ERROR] Could not retrieve inventory: {e}")
