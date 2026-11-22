"""The SIP account: REGISTER results and incoming calls."""

from .._native import pjsua2 as pj
from ..events import PhoneEvents as P
from .call import Call, destroy_native

ONLINE = {pj.PJSUA_BUDDY_STATUS_ONLINE: True, pj.PJSUA_BUDDY_STATUS_OFFLINE: False}


class Buddy(pj.Buddy):
    """Someone this account watches (presence SUBSCRIBE) or types to.
    Dialog state (BLF) comes from the NOTIFYs themselves: see LogWriter."""

    def __init__(self, account, uri, presence=False, dialog=False):
        super().__init__()
        self.account, self.uri = account, uri
        config = pj.BuddyConfig()
        config.uri, config.subscribe = uri, presence
        config.subscribe_dlg_event = dialog
        self.create(account, config)

    def onBuddyState(self):
        status = self.getInfo().presStatus
        self.account.endpoint.emit(
            P.Presence,
            uri=self.uri,
            online=ONLINE.get(status.status),
            status=status.statusText,
            note=status.note,
            account_id=self.account.account_id,
        )


class Account(pj.Account):
    def __init__(self, endpoint, config, password=None):
        super().__init__()
        self.endpoint = endpoint
        self.config = config
        self.account_id = config.account_id
        self.password = password
        self.registered = False
        self.buddies: dict[str, Buddy] = {}  # uri -> Buddy

    def buddy(self, uri):
        """The Buddy for `uri`, created (without subscriptions) if new."""
        if uri not in self.buddies:
            self.buddies[uri] = Buddy(self, uri)
        return self.buddies[uri]

    def subscribe(self, uri, dialog=False):
        """PJSUA keeps one subscription per buddy: presence, or dialog (BLF)."""
        self.unsubscribe(uri)
        self.buddies[uri] = Buddy(self, uri, presence=not dialog, dialog=dialog)

    def unsubscribe(self, uri):
        buddy = self.buddies.pop(uri, None)
        destroy_native(buddy)  # ends its subscriptions

    def drop_buddies(self):
        for uri in list(self.buddies):
            self.unsubscribe(uri)

    def set_presence(self, online=True, note=""):
        status = pj.PresenceStatus()
        status.status = (
            pj.PJSUA_BUDDY_STATUS_ONLINE if online else pj.PJSUA_BUDDY_STATUS_OFFLINE
        )
        status.note = note
        self.setOnlineStatus(status)

    def send_typing(self, uri, typing=True):
        params = pj.SendTypingIndicationParam()
        params.isTyping = typing
        self.buddy(uri).sendTypingIndication(params)

    def onRegState(self, prm):
        info = self.getInfo()
        code = int(info.regStatus)
        self.registered = bool(info.regIsActive)
        reason, active = info.regStatusText, self.registered
        self.endpoint.emit(
            P.Registration,
            code=code,
            reason=reason,
            active=active,
            account_id=self.account_id,
        )
        if active and 200 <= code < 300:
            self.endpoint.emit(
                P.Registered, code=code, reason=reason, account_id=self.account_id
            )
        # PJSUA answers the Digest challenge itself: a 401/407 here is final
        # (wrong password, or none).
        if code >= 300:
            self.endpoint.emit(
                P.RegistrationFailed,
                code=code,
                reason=reason,
                account_id=self.account_id,
            )

    def onSendRequest(self, prm):
        # Final response to a request sent with Endpoint.send_request().
        try:
            tsx = prm.e.body.tsxState.tsx
            self.endpoint.emit(
                P.Response,
                method=tsx.method,
                code=tsx.statusCode,
                reason=tsx.statusText,
                account_id=self.account_id,
            )
        except AttributeError, pj.Error:
            pass

    def onInstantMessage(self, prm):
        self.endpoint.emit(
            P.Message,
            from_uri=prm.fromUri,
            content_type=prm.contentType,
            body=prm.msgBody,
            account_id=self.account_id,
        )

    def onMwiInfo(self, prm):
        message = prm.rdata.wholeMsg.replace("\r\n", "\n")
        body = message.partition("\n\n")[2].strip()
        waiting = "messages-waiting: yes" in body.lower()
        self.endpoint.emit(
            P.Mwi, waiting=waiting, body=body, account_id=self.account_id
        )

    def onTypingIndication(self, prm):
        self.endpoint.emit(
            P.Typing,
            from_uri=prm.fromUri,
            typing=bool(prm.isTyping),
            account_id=self.account_id,
        )

    def onIncomingCall(self, prm):
        # The Call object must exist before this callback returns, or PJSUA2
        # rejects the INVITE on its own with a 500.
        call = Call(self, self.endpoint, prm.callId)
        info = call.getInfo()
        self.endpoint.dialogs[(self.account_id, info.callIdString)] = call.ref
        self.endpoint.offer(call)
