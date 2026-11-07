"""Actual UDP/TCP discovery across separate processes; no ZeroTier required."""
import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import pytest
from lantool.netcore.beacon import BeaconListener, parse_beacon, make_beacon
from lantool.netcore.discovery import QUERY, fetch_room
from lantool.trust.signing import generate_keypair

SERVER = '''
import asyncio,json
from lantool.netcore.discovery import DiscoveryResponder
from lantool.netcore.beacon import make_beacon
from lantool.trust.signing import generate_keypair
from lantool.trust.planet_transport import PlanetServer
async def main():
    private,public=generate_keypair()
    http=PlanetServer(private,'unused',host='127.0.0.1',port=0)
    def payload(address):
        return make_beacon(private,'abcdef0123456789',address,47800,'hash','test',host_pub=public,host_zt='10.147.20.1',planet_port=http.port)
    http.room_payload=payload
    await http.start()
    udp=await DiscoveryResponder.start(payload,host='127.0.0.1',port=0)
    print(json.dumps(dict(udp=udp.get_extra_info('sockname')[1],tcp=http.port,pub=public)),flush=True)
    try: await asyncio.sleep(60)
    finally:
        udp.close()
        await http.stop()
asyncio.run(main())
'''


async def test_active_discovery_and_direct_ip_across_processes():
    env=dict(os.environ)
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+env.get('PYTHONPATH','')
    process=await asyncio.create_subprocess_exec(sys.executable,'-u','-c',SERVER,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
    transport=None
    try:
        config=json.loads(await asyncio.wait_for(process.stdout.readline(),10))
        found=asyncio.get_running_loop().create_future()
        def seen(beacon):
            if not found.done(): found.set_result(beacon)
        transport,_=await asyncio.get_running_loop().create_datagram_endpoint(
            lambda:BeaconListener(config['pub'],seen),local_addr=('127.0.0.1',0),allow_broadcast=True)
        transport.sendto(QUERY,('127.0.0.1',config['udp']))
        beacon=await asyncio.wait_for(found,5)
        assert beacon['host']=='127.0.0.1'
        assert beacon['net_id']=='abcdef0123456789'
        direct=await fetch_room('127.0.0.1',config['tcp'])
        assert direct['host_pub']==config['pub']
        assert direct['net_id']==beacon['net_id']
    finally:
        if transport: transport.close()
        if process.returncode is None: process.terminate()
        await process.wait()


def test_signed_malformed_timestamp_does_not_crash_listener():
    from lantool.trust.signing import sign_obj
    private,public=generate_keypair()
    body=json.loads(make_beacon(private,'n','127.0.0.1',47800,'h','1',host_pub=public))
    body['ts']='invalid'
    assert parse_beacon(json.dumps(sign_obj(private,body)).encode()) is None


def test_firewall_is_program_and_port_scoped():
    from silent_tunnel.firewall import apply_rules
    with patch('silent_tunnel.firewall.subprocess.run') as run:
        run.return_value.returncode=0
        apply_rules()
        command=run.call_args.args[0][-1]
        assert '-Program ' in command
        assert '-RemoteAddress LocalSubnet,10.147.0.0/16' in command
        assert '-LocalPort 47801,47804,47806' in command
        assert '-LocalPort 47800,47802,47803,47805' in command
