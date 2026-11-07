"""UI orchestration for the separately authorized Host release handoff."""
import asyncio
import concurrent.futures
import re
import secrets
import time
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog
from ..netcore.launcher_share import exchange, download


def offer(bridge, beacon, message, allow_host_switch=False):
    if (bridge.role != 'client'
            or bridge._upgrade and bridge._upgrade.get('status') not in ('mismatch', 'error')
            or getattr(bridge, '_upgrade_future', None) and not bridge._upgrade_future.done()):
        return
    bridge._paused_version_room = beacon.get('net_id')
    bridge._upgrade_beacon = dict(beacon)
    version = str(beacon.get('version', ''))
    meta = beacon.get('launcher_share')
    supported = bool(isinstance(meta, dict) and meta.get('protocol') == 1 and re.fullmatch(r'\d+\.\d+\.\d+', version))
    pinned = getattr(bridge, 'trusted_host_pub', None)
    trusted = not pinned or pinned == beacon.get('host_pub') or allow_host_switch
    reason = ('This announcement does not match your saved Host. Select the intended Host explicitly by Room ID or IP before requesting its launcher.'
              if not trusted else 'This Host cannot share its launcher version. Copy the release manually, or update the Host to a release with launcher sharing.')
    bridge._upgrade = dict(status='mismatch', version=version, supported=supported, message=message,
                          done=0, total=0, unavailableReason=reason,
                          host=str(beacon.get('pc_name') or beacon.get('host', '')),
                          address=str((meta.get('host') if isinstance(meta, dict) else None) or beacon.get('host', '')))
    bridge._upgrade['supported'] = supported and trusted
    bridge._dialog = {}
    bridge.publish()


def update(bridge, epoch, **changes):
    if epoch != getattr(bridge, '_upgrade_epoch', 0) or bridge._closing:
        return
    bridge._upgrade = {**(bridge._upgrade or {}), **changes}
    bridge.publish()


def schedule(bridge, work, epoch):
    future = bridge.runtime.submit(work)
    bridge._upgrade_future = future
    # Bind exception text immediately; Python clears the except variable.
    def complete(done):
        try:
            done.result()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            return
        except Exception as exc:
            message = str(exc)
            bridge.after(0, lambda: update(bridge, epoch, status='error', message=message))
    future.add_done_callback(complete)


def request(bridge):
    if (bridge._preview or not bridge._upgrade or not bridge._upgrade.get('supported')
            or bridge._upgrade.get('status') not in ('mismatch', 'error')):
        return
    if bridge._upgrade_future and not bridge._upgrade_future.done():
        return
    if bridge._upgrade_client:
        previous = dict(bridge._upgrade)
        cancel(bridge)
        bridge._upgrade = previous
    bridge._upgrade_epoch += 1
    epoch = bridge._upgrade_epoch
    context = dict(beacon=dict(bridge._upgrade_beacon), secret=secrets.token_hex(32))
    bridge._upgrade_client = context
    update(bridge, epoch, status='requesting', message='Requesting the Host launcher version...')
    async def run():
        response = await exchange(context['beacon'], dict(action='request', secret=context['secret'], name=bridge.config_data.get('player_name', bridge.pc_name)))
        if response.get('status') != 'pending':
            raise ValueError('The Host is busy or the request limit was reached. Try again later.')
        context['id'] = response['id']
        while epoch == bridge._upgrade_epoch:
            result = await exchange(context['beacon'], dict(action='poll', id=context['id'], secret=context['secret']))
            status = result['status']
            if status == 'approved':
                bridge.after(0, lambda: update(bridge, epoch, status='pin', message='Host accepted. Ask the Host for the three-digit pass key.'))
                return
            if status not in ('pending', 'preparing'):
                raise ValueError(result.get('error') or 'The Host denied the request, or it expired.')
            text = 'Waiting for Host approval...' if status == 'pending' else 'Host is preparing the launcher package...'
            bridge.after(0, lambda text=text: update(bridge, epoch, status='waiting', message=text))
            await asyncio.sleep(1)
    schedule(bridge, run(), epoch)


def unlock(bridge, pin):
    if (bridge._preview or not bridge._upgrade or bridge._upgrade.get('status') != 'pin'
            or not re.fullmatch(r'\d{3}', pin) or bridge._upgrade_future and not bridge._upgrade_future.done()):
        return
    epoch, context = bridge._upgrade_epoch, bridge._upgrade_client
    update(bridge, epoch, status='unlocking', message='Checking pass key...')
    async def run():
        result = await exchange(context['beacon'], dict(action='unlock', id=context['id'], secret=context['secret'], pin=pin))
        if result['status'] == 'wrong_pin':
            bridge.after(0, lambda: update(bridge, epoch, status='pin', message='Incorrect pass key. Three wrong attempts end this request.'))
            return
        if result['status'] != 'ready':
            raise ValueError('Pass-key verification failed, or the request expired. Request approval again.')
        context['token'] = result['token']
        bridge.after(0, choose_destination, bridge, epoch)
    schedule(bridge, run(), epoch)


def choose_destination(bridge, epoch):
    if (epoch != bridge._upgrade_epoch or not bridge._upgrade or not bridge._upgrade_client
            or not bridge._upgrade_client.get('token') or bridge._upgrade.get('status') not in ('unlocking', 'destination')):
        return
    update(bridge, epoch, status='destination', message='Pass key accepted. Choose where to save the Host launcher ZIP.')
    folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    filename = f"LAN Launcher V{bridge._upgrade['version']}.zip"
    destination = QFileDialog.getSaveFileName(None, 'Save Host launcher version', str(Path(folder)/filename), 'Launcher ZIP (*.zip)')[0]
    if not destination:
        cancel(bridge)
        return
    from .. import launcher as core
    if Path(destination).resolve().is_relative_to(core.APP_DIR.resolve()):
        update(bridge, epoch, status='destination', message='Choose a folder outside launcher data, such as Downloads, so VLA cleanup keeps the downloaded ZIP.')
        return
    if Path(destination).exists():
        update(bridge, epoch, status='destination', message='That filename already exists. Choose a new filename to keep the existing file.')
        return
    context = bridge._upgrade_client
    update(bridge, epoch, status='downloading', message='Downloading and verifying the Host launcher package...')
    last_progress = [0.0]
    def progress(done, total):
        now = time.monotonic()
        if done < total and now-last_progress[0] < .2:
            return
        last_progress[0] = now
        bridge.after(0, lambda: update(bridge, epoch, done=done, total=total))
    async def run():
        path = await download(context['beacon'], dict(id=context['id'], secret=context['secret'], token=context['token']), destination, progress)
        bridge.after(0, completed, bridge, epoch, path)
    schedule(bridge, run(), epoch)


def completed(bridge, epoch, path):
    if epoch != bridge._upgrade_epoch:
        return
    bridge._launcher_upgrade_download = path
    update(bridge, epoch, status='complete', message='Download verified: '+path+'\n\nClose this Client and clean the old VLA files before using the downloaded version. Use Repair Network/Wipe VLA to clean and close the Client, then extract the ZIP and open the new Client.')


def cancel(bridge):
    bridge._upgrade_epoch += 1
    future = bridge._upgrade_future
    if future and not future.done():
        future.cancel()
    context = bridge._upgrade_client
    if context and context.get('id') and not bridge._closing:
        async def revoke():
            try:
                await exchange(context['beacon'], dict(action='cancel', id=context['id'], secret=context['secret']))
            except (OSError, ValueError, asyncio.TimeoutError):
                pass
        bridge.runtime.submit(revoke())
    bridge._upgrade = None
    bridge._upgrade_client = None
    bridge.publish()
