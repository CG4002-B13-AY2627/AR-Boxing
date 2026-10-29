"""Two simulated phones against a running authority, with verified TLS by default."""
import argparse
import asyncio
import json
import ssl
import uuid
import websockets
from contract_validation import validator


async def run(args):
    tls = ssl.create_default_context(cafile=args.ca) if args.url.startswith("wss://") else None
    sockets, latest = {}, {}
    counts = dict(punches=0, pickups=0, results=0)
    pending = asyncio.Queue()
    serial = 0
    async def send_command(player, name):
        nonlocal serial
        serial += 1
        welcome = welcomes[player]
        await sockets[player].send(json.dumps(dict(type="PlayerCommand",protocol_version=2,
            match_id=welcome["match_id"],stream_id=welcome["stream_id"],player_id=player,
            command_id="probe-"+str(serial),command=name,timestamp=0)))
    async def pump(player):
        async for raw in sockets[player]:
            value=json.loads(raw)
            names={"MatchState":"match-state","GameEvent":"game-event","PunchAttempt":"punch-attempt",
                   "PickupCheck":"pickup-check","PickupResult":"pickup-result"}
            validator(names[value["type"]]).validate(value)
            if value["type"]=="MatchState": latest[player]=value
            elif value["type"]=="PunchAttempt":
                await sockets[player].send(json.dumps(dict(type="PunchObservation",protocol_version=2,
                    match_id=value["match_id"],stream_id=value["stream_id"],attack_id=value["attack_id"],
                    observer_player=player,observation="TARGET_TRACKED",target_age_ms=0,client_timestamp=0)))
            elif value["type"]=="PickupCheck":
                reply={k:value[k] for k in ("match_id","stream_id","request_id","item_id","player_id")}
                reply.update(type="PickupObservation",protocol_version=2,observation="AVAILABLE",
                             observed_distance_m=.25,hand="LEFT",client_timestamp=0)
                await sockets[player].send(json.dumps(reply))
            elif value["type"]=="PickupResult" and value["accepted"]: counts["results"]+=1
            elif value["type"]=="GameEvent" and player==1:
                if value["event"]=="PUNCH": counts["punches"]+=1
                if value["event"]=="ITEM_PICKUP": counts["pickups"]+=1
            await pending.put((player,value))
    welcomes={}
    tasks=[]
    try:
        for player in (1,2):
            ws=await websockets.connect(args.url,ssl=tls)
            sockets[player]=ws
            await ws.send(json.dumps(dict(type="ClientHello",protocol_version=2,
                client_id="probe-"+args.identity+"-p"+str(player),player_id=player)))
            welcome=json.loads(await asyncio.wait_for(ws.recv(),5))
            validator("server-welcome").validate(welcome)
            if not welcome.get("supports_player_commands"): raise AssertionError("server lacks menu commands")
            welcomes[player]=welcome
        tasks=[asyncio.create_task(pump(p)) for p in sockets]
        for action,phase in (("READY","CALIBRATING"),("CALIBRATED","FIGHTING")):
            # Initial and post-command states are asynchronous; use complete snapshots.
            if action=="READY":
                while len(latest)<2: await pending.get()
            for p in sockets: await send_command(p,action)
            while not all(latest[p]["state"]==phase for p in sockets): await pending.get()
        await send_command(1,"PAUSE")
        while not all(latest[p]["state"]=="PAUSED" for p in sockets): await pending.get()
        for p in sockets: await send_command(p,"RESUME")
        while not all(latest[p]["state"]=="MATCH_END" for p in sockets):
            for task in tasks:
                if task.done(): task.result(); raise AssertionError("phone disconnected before match end")
            await asyncio.wait_for(pending.get(),5)
        for field in ("state","match_result","player_1","player_2","active_items"):
            if latest[1][field]!=latest[2][field]: raise AssertionError("clients disagree: "+field)
        if counts["punches"]<1 or counts["pickups"]<2 or counts["results"]<2:
            raise AssertionError("incomplete scenario: "+str(counts))
        print("Full multiplayer smoke passed:",counts,"result="+latest[1]["match_result"])
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.gather(*(ws.close() for ws in sockets.values()),return_exceptions=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="wss://127.0.0.1:8889")
    parser.add_argument("--ca")
    parser.add_argument("--timeout",type=float,default=45)
    parser.add_argument("--identity",default=uuid.uuid4().hex[:12])
    args=parser.parse_args()
    async def bounded(): await asyncio.wait_for(run(args),args.timeout)
    asyncio.run(bounded())
