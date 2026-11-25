"""Endpoint, accounts and calls. Every operation runs on the engine thread."""

from __future__ import annotations

import contextlib
import ctypes
import gc
import os
import re
import time
from dataclasses import replace

from .._native import pjsua2 as pj
from ..events import CallEvents as C
from ..events import PhoneEvents as P
from ..models import Report
from .account import Account
from .call import Call, add_headers
from .config import PRACK, SESSION_TIMER
from .profiles import ENDPOINT_FIELDS
from .sip import dialog_state, parse_trace

DEFAULT_CAPTURE, DEFAULT_PLAYBACK = -1, -2


@contextlib.contextmanager
def quiet_stdout():
    """Drop what C code writes to stdout: libCreate() prints pjlib's start-up
    log there, before the LogWriter is installed by libInit()."""
    libc = ctypes.CDLL(None)
    libc.fflush(None)
    saved, devnull = os.dup(1), os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    try:
        yield
    finally:
        libc.fflush(None)
        os.dup2(saved, 1)
        os.close(saved)
        os.close(devnull)


class LogWriter(pj.LogWriter):
    def __init__(self, endpoint):
        super().__init__()
        self.endpoint: Endpoint | None = endpoint

    def write(self, entry):
        endpoint = self.endpoint
        if endpoint is None:
            return
        try:
            msg = parse_trace(entry.msg)
            if msg is not None:
                identity = endpoint.sip_identity(msg)
                kind = C.Sip if identity["ref"] else P.Sip
                endpoint.emit(kind, message=msg, call_id=msg.call_id, **identity)
                blf = dialog_state(msg)
                if blf is not None:
                    uri, state, body = blf
                    owner = identity["account_id"] or endpoint.config.account_id
                    endpoint.emit(
                        P.DialogState, uri=uri, state=state, body=body, account_id=owner
                    )
            if entry.level <= endpoint.config.log_level:
                endpoint.emit(P.Log, level=entry.level, text=entry.msg.rstrip("\n"))
        except Exception:  # noqa: BLE001, S110 - boundary reports errors without stopping callbacks/workers
            pass


class Library(pj.Endpoint):
    """pj.Endpoint with the callbacks that belong to no account."""

    def __init__(self, endpoint):
        super().__init__()
        self.endpoint: Endpoint | None = endpoint

    def onRejectedIncomingCall(self, prm):
        endpoint = self.endpoint
        if endpoint is None:
            return
        # The account the INVITE was for (its To), else the first one.
        owner = next(
            (
                a.account_id
                for a in endpoint.accounts.values()
                if f"sip:{a.config.user}@" in prm.localInfo
            ),
            endpoint.config.account_id,
        )
        endpoint.emit(
            P.Rejected,
            code=prm.statusCode,
            reason=prm.reason,
            remote_uri=prm.remoteInfo,
            call_id=prm.callId,
            account_id=owner,
        )

    def onNatDetectionComplete(self, prm):
        if self.endpoint is not None:
            self.endpoint.emit(
                P.Nat, type=prm.natTypeName, ok=prm.status == 0, reason=prm.reason
            )


class Endpoint:
    def __init__(self, config, listener=None):
        self.config = config
        self.listener = listener or (lambda event: None)
        self._lib: Library | None = Library(self)
        self.writer: LogWriter | None = LogWriter(self)
        self.accounts = {}
        self.calls = {}
        self.audio = None
        self.created = False
        self.dialogs: dict[tuple[str, str], str | None] = {}
        self.dialing: str | None = None

    @property
    def lib(self) -> Library:
        """The PJSUA2 library object (a native singleton)."""
        if self._lib is None:
            raise RuntimeError("Endpoint has been destroyed")
        return self._lib

    @property
    def account(self):
        return self.accounts.get(self.config.account_id) or next(
            iter(self.accounts.values()), None
        )

    def emit(self, kind, **fields):
        """Create a typed event (kind: a CallEvents/PhoneEvents class)."""
        fields.setdefault("account_id", self.config.account_id)
        self.listener(kind(**fields))

    def warn(self, text, **identity):
        self.emit(P.Warning, text=text, **identity)

    def sip_identity(self, msg):
        """Resolve the local leg, including two local accounts sharing a Call-ID."""
        owner, ref = self._leg(msg, self._local_owner(msg))
        if msg.call_id and owner is not None:
            self.dialogs[(owner, msg.call_id)] = ref
            if len(self.dialogs) > 2000:
                self.dialogs.pop(next(iter(self.dialogs)))
        return {"account_id": owner, "ref": ref}

    def _local_owner(self, msg):
        """The one local account named in our side's From (or To), or None."""
        local_header = "from" if (msg.is_request == (msg.direction == "TX")) else "to"
        match = re.search(
            r"sips?:([^@<>;\s]+)@([^:;>\s]+)", msg.headers.get(local_header, "")
        )
        if not match:
            return None
        owners = [
            a.account_id
            for a in self.accounts.values()
            if a.config.user == match[1] and a.config.domain.lower() == match[2].lower()
        ]
        return owners[0] if len(owners) == 1 else None

    def _leg(self, msg, owner):
        """(account_id, call ref) of a message; `owner` may be None (unknown)."""
        incoming_invite = msg.direction == "RX" and msg.method == "INVITE"
        if msg.direction == "TX" and msg.method == "INVITE":
            pending = self.calls.get(self.dialing)
            if pending is not None:
                return pending.account_id, pending.ref
        calls = [
            c
            for c in self.calls.values()
            if c.last.get("call_id") == msg.call_id
            and (owner is None or c.account_id == owner)
        ]
        untagged = incoming_invite and ";tag=" not in msg.headers.get("to", "")
        if len(calls) == 1 and (owner is not None or not untagged):
            return calls[0].account_id, calls[0].ref
        if owner is not None:
            return owner, self.dialogs.get((owner, msg.call_id))
        known = [
            (account, ref)
            for (account, call_id), ref in self.dialogs.items()
            if call_id == msg.call_id
        ]
        if len(known) == 1 and not incoming_invite:
            return known[0]
        return None, None

    def __enter__(self):
        try:
            opt = self.config
            with quiet_stdout():
                self.lib.libCreate()
            self.created = True
            config = pj.EpConfig()
            config.uaConfig.threadCnt = 0
            config.uaConfig.mainThreadOnly = True
            config.uaConfig.maxCalls = opt.max_calls
            for server in opt.stun_servers:
                config.uaConfig.stunServer.append(server)
            config.logConfig.writer = self.writer
            config.logConfig.level = config.logConfig.consoleLevel = max(
                opt.log_level, 4
            )
            config.medConfig.noVad = True
            config.medConfig.ecTailLen = opt.ec_tail
            self.lib.libInit(config)
            transport = pj.TransportConfig()
            transport.port = opt.local_port
            transport.boundAddress = opt.bind_address
            transport.publicAddress = opt.public_address
            if opt.transport == "tls":
                transport.tlsConfig.CaListFile = opt.tls_ca_file
                transport.tlsConfig.verifyServer = opt.tls_verify
            kind = getattr(pj, f"PJSIP_TRANSPORT_{opt.transport.upper()}")
            self.transport_id = self.lib.transportCreate(kind, transport)
            self.lib.libStart()
            self.setup_audio()
            wanted = ["PCMA", "PCMU"] if opt.codec == "auto" else opt.codec.split(",")
            found = set()
            for codec in self.lib.codecEnum2():
                name = codec.codecId.split("/")[0].upper()
                rank = next(
                    (i for i, c in enumerate(wanted) if c.upper() == name), None
                )
                self.lib.codecSetPriority(
                    codec.codecId, 255 - rank if rank is not None else 0
                )
                if rank is not None:
                    found.add(wanted[rank])
            if set(wanted) - found:
                raise ValueError(
                    f"Codec unavailable in this build: {sorted(set(wanted) - found)}"
                )
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *exc):
        if not self.created:
            return
        try:
            # Each step runs in its own method so no local keeps a native
            # object alive past gc.collect().
            self._end_calls()
            gc.collect()
            self._close_accounts()
            gc.collect()
        finally:
            self.lib.libDestroy()
            self.created = False
            # Endpoint is a native singleton. libDestroy alone does not delete
            # the C++ object; break the writer/endpoint cycle before another start.
            if self._lib is not None:
                self._lib.endpoint = None
            self._lib = None
            if self.writer is not None:
                self.writer.endpoint = None
            self.writer = None

    def _end_calls(self, wait=5):
        """Hang up every call and give them `wait` seconds to end."""
        for call in list(self.calls.values()):
            call.release_media()
            if not call.ended_at and call.getId() >= 0:
                try:
                    call.hangup(pj.CallOpParam())
                except pj.Error as error:
                    self.warn(error.info())
        deadline = time.monotonic() + wait
        while (
            any(not c.ended_at for c in self.calls.values())
            and time.monotonic() < deadline
        ):
            self.poll()
        self.calls.clear()

    def _close_accounts(self):
        """Drop buddies, unregister and shut down every account."""
        for account in self.accounts.values():
            try:
                account.drop_buddies()
                if account.registered:
                    account.setRegistration(False)
                    self.poll(0.1)
                account.shutdown()
            except pj.Error as error:
                self.warn(error.info())
        self.accounts.clear()

    def poll(self, seconds=0.0, step_ms=50):
        deadline = time.monotonic() + seconds
        while True:
            self.lib.libHandleEvents(step_ms)
            if time.monotonic() >= deadline:
                return

    def setup_audio(self, opt=None):
        opt = opt or self.config
        needs_card = (
            opt.media == "mic"
            or opt.speaker
            or any(
                c.config.media == "mic" or c.config.speaker
                for c in self.calls.values()
                if not c.ended_at
            )
        )
        wanted = (needs_card, self.config.capture_device, self.config.playback_device)
        if wanted == self.audio:
            return
        devices = self.lib.audDevManager()
        uses_card, capture, playback = wanted
        if not uses_card:
            devices.setNullDev()
        else:
            # PJSUA takes any index here and then sends silence: check it.
            count = devices.getDevCount()
            for name, index in (
                ("capture_device", capture),
                ("playback_device", playback),
            ):
                if index is not None and not 0 <= index < count:
                    raise ValueError(
                        f"{name}={index}: no such audio device (see simple-phone devices)"
                    )
            devices.setCaptureDev(DEFAULT_CAPTURE if capture is None else capture)
            devices.setPlaybackDev(DEFAULT_PLAYBACK if playback is None else playback)
        self.audio = wanted

    def configure(self, changes, account_id=None):
        allowed = {
            "media",
            "wav",
            "speaker",
            "record",
            "capture_device",
            "playback_device",
            "amd",
        }
        if set(changes) - allowed:
            raise ValueError("Only media/device settings can change at runtime")
        config = self.accounts[account_id].config if account_id else self.config
        updated = replace(config, **changes)
        for key in changes:
            setattr(config, key, getattr(updated, key))

    def devices(self):
        # The id is the position in this list, as setCaptureDev() takes it.
        # AudioDevInfo.id is a pjmedia_aud_dev_index, which SWIG returns as
        # an opaque pointer (and warns about a leak when it is freed).
        found = self.lib.audDevManager().enumDev2()
        return [
            {
                "id": index,
                "name": d.name,
                "driver": d.driver,
                "inputs": d.inputCount,
                "outputs": d.outputCount,
            }
            for index, d in enumerate(found)
        ]

    def codecs(self):
        return [
            {"id": c.codecId, "priority": c.priority} for c in self.lib.codecEnum2()
        ]

    def handle_ip_change(self):
        self.lib.handleIpChange(pj.IpChangeParam())

    def validate_account(self, opt):
        if not opt.account_id or any(c.isspace() for c in opt.account_id):
            raise ValueError("account_id must be nonempty, without spaces")
        if opt.account_id in self.accounts:
            raise ValueError(f"Account already exists: {opt.account_id}")
        shared = sorted(
            key
            for key in ENDPOINT_FIELDS
            if getattr(opt, key) != getattr(self.config, key)
        )
        if shared:
            raise ValueError(
                f"{', '.join(shared)}: shared by all accounts, set on the first one"
            )
        for account in self.accounts.values():
            if abs(account.config.rtp_port - opt.rtp_port) < 102:
                raise ValueError(
                    "Accounts need separate RTP/RTCP port ranges (at least 102 ports apart)"
                )

    def account_config(self, opt, password):
        config = pj.AccountConfig()
        config.idUri = f"sip:{opt.user}@{opt.domain}"
        config.regConfig.registrarUri = (
            f"sip:{opt.server}:{opt.port};transport={opt.transport}"
        )
        config.regConfig.registerOnAdd = opt.register and opt.auto_register
        config.regConfig.disableRegOnModify = not (opt.register and opt.auto_register)
        config.sipConfig.transportId = self.transport_id
        if password is not None:
            config.sipConfig.authCreds.append(
                pj.AuthCredInfo("digest", "*", opt.auth_user or opt.user, 0, password)
            )
        if opt.proxy:
            config.sipConfig.proxies.append(opt.proxy)
        config.mediaConfig.transportConfig.port = opt.rtp_port
        config.mediaConfig.transportConfig.portRange = 100
        config.mediaConfig.transportConfig.publicAddress = opt.public_address
        config.natConfig.iceEnabled = opt.ice
        config.natConfig.turnEnabled = bool(opt.turn_server)
        config.natConfig.turnServer = opt.turn_server
        config.natConfig.turnUserName = opt.turn_user
        config.natConfig.turnPassword = opt.turn_password
        config.mediaConfig.srtpUse = getattr(pj, f"PJMEDIA_SRTP_{opt.srtp.upper()}")
        config.callConfig.prackUse = PRACK.index(opt.prack)
        config.callConfig.timerUse = SESSION_TIMER.index(opt.session_timer)
        config.mwiConfig.enabled = opt.mwi
        # Keep the stack's secure-signaling policy for SDES keys.
        return config

    def open_account(self, password=None, config=None):
        opt = config or self.config
        self.validate_account(opt)
        native = self.account_config(opt, password)
        account = Account(self, opt, password)
        self.accounts[opt.account_id] = account
        try:
            account.create(native)
        except pj.Error:
            account.shutdown()
            del self.accounts[opt.account_id]
            raise
        return opt.account_id

    def account_for(self, account_id=None):
        account = self.accounts[account_id] if account_id else self.account
        if account is None:
            raise RuntimeError("No SIP account")
        return account

    def set_registration(self, active, account_id=None):
        account = self.account_for(account_id)
        account.setRegistration(active)

    def start_call(self, target, headers=(), account_id=None, ref=None):
        """Dial; the call takes `ref` (or a new one). Returns the URI dialed."""
        self.reap()
        if len(self.calls) >= self.config.max_calls:
            raise RuntimeError("Call limit reached")
        account = self.account_for(account_id)
        destination = self.verified_uri(account.config.uri(target))
        self.setup_audio(account.config)
        call = Call(account, self, ref=ref)
        params = call.media_op()
        add_headers(params.txOption, headers)
        self.calls[call.ref] = call
        self.dialing = call.ref
        try:
            call.makeCall(destination, params)
        except pj.Error:
            self.calls.pop(call.ref)
            raise
        finally:
            self.dialing = None
        return destination

    def verified_uri(self, uri):
        if self.lib.utilVerifySipUri(uri) != 0:
            raise ValueError(f"Not a valid SIP URI: {uri}")
        return uri

    def send_request(
        self, method, target, headers=(), body="", content_type="", account_id=None
    ):
        """Out-of-dialog request (OPTIONS, MESSAGE, NOTIFY...). The final
        response arrives as a `response` event from the account."""
        account = self.account_for(account_id)
        params = pj.SendRequestParam()
        params.method = method.upper()
        params.txOption.targetUri = self.verified_uri(account.config.uri(target))
        add_headers(params.txOption, headers)
        if body:
            params.txOption.contentType = content_type or "text/plain"
            params.txOption.msgBody = body
        account.sendRequest(params)

    def subscribe(self, target, dialog=False, account_id=None):
        """Presence (and, with dialog, BLF) of `target`. Returns its URI."""
        account = self.account_for(account_id)
        uri = self.verified_uri(account.config.uri(target))
        account.subscribe(uri, dialog)
        return uri

    def unsubscribe(self, target, account_id=None):
        account = self.account_for(account_id)
        account.unsubscribe(account.config.uri(target))

    def set_presence(self, online=True, note="", account_id=None):
        self.account_for(account_id).set_presence(online, note)

    def send_typing(self, target, typing=True, account_id=None):
        account = self.account_for(account_id)
        account.send_typing(self.verified_uri(account.config.uri(target)), typing)

    def detect_nat(self):
        """Classify the NAT via STUN (stun_servers); the result is a Nat event."""
        if not self.config.stun_servers:
            raise RuntimeError("NAT detection needs stun_servers")
        self.lib.natDetectType()

    def child_call(self, parent):
        """The Call for a call that a REFER or a Replaces starts from `parent`.
        PJSUA2 needs a new object; otherwise both calls share `parent`, and
        finish() deleting it leaves the other with a dangling pointer."""
        call = Call(self.accounts[parent.account_id], self)
        self.calls[call.ref] = call
        return call

    def offer(self, call):
        self.calls[call.ref] = call  # retain even a rejected call until DISCONNECTED
        if len(self.calls) <= self.config.max_calls:
            call.pending = True
            info = call.getInfo()
            self.emit(
                P.Incoming,
                remote_uri=info.remoteUri,
                **call.identity(info.callIdString),
            )
            params = pj.CallOpParam()
            params.statusCode = 180
            call.answer(params)
        else:
            call.pending = False
            params = pj.CallOpParam()
            params.statusCode = 486
            call.hangup(params)

    def finish(self, call):
        """A call is over: report it and let go of it.

        Called from the DISCONNECTED callback, before PJSUA can give the call
        slot to a new call. Deleting the object later made ~Call clear the
        slot's user data (and hang up) for whichever call reused the slot.
        """
        if self.calls.get(call.ref) is not call:
            return
        report = call.report()
        call.release_media()
        identity = call.identity()
        del self.calls[call.ref]
        self.emit(C.Ended, report=Report.parse(report), **identity)

    def reap(self):
        """Fallback for calls that ended without a DISCONNECTED callback."""
        for call in [c for c in self.calls.values() if c.ended_at]:
            self.finish(call)
        # A REFER/Replaces child gets its ID inside the same poll() that made
        # it. Still without one afterwards, the new call never started.
        for call in [c for c in self.calls.values() if c.getId() < 0]:
            del self.calls[call.ref]
