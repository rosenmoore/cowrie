# Copyright (c) 2009-2014 Upi Tamminen <desaster@gmail.com>
# See the COPYRIGHT file for more information

"""
This module contains ...
"""

from sys import modules

from zope.interface import implementer

from pyelliptic import ECC
from base64 import b64decode
from base64 import b64encode

from twisted.cred.checkers import ICredentialsChecker
from twisted.cred.credentials import ISSHPrivateKey
from twisted.cred.error import UnauthorizedLogin, UnhandledCredentials
from twisted.internet import defer
from twisted.python import log, failure
from twisted.conch import error
from twisted.conch.ssh import keys

from cowrie.core import credentials
from cowrie.core import auth

@implementer(ICredentialsChecker)
class HoneypotPublicKeyChecker(object):
    """
    Checker that accepts, logs and denies public key authentication attempts
    """

    credentialInterfaces = (ISSHPrivateKey,)

    def requestAvatarId(self, credentials):
        """
        """
        _pubKey = keys.Key.fromString(credentials.blob)
        log.msg(eventid='cowrie.client.fingerprint',
                format='public key attempt for user %(username)s with fingerprint %(fingerprint)s',
                username=credentials.username,
                fingerprint=_pubKey.fingerprint())
        return failure.Failure(error.ConchError('Incorrect signature'))



@implementer(ICredentialsChecker)
class HoneypotNoneChecker(object):
    """
    Checker that does no authentication check
    """

    credentialInterfaces = (credentials.IUsername,)

    def requestAvatarId(self, credentials):
        """
        """
        return defer.succeed(credentials.username)


class PasswordCrypto:
    """
    Small wrapper around pyelliptic to perform assymetric encryption of
    passwords.
    """

    def __init__(self, pubkey):
        self.pubkey = b64decode(pubkey)
        self.actor = ECC(pubkey=self.pubkey)

    def encrypt(self, pwd):
        return b64encode(self.actor.encrypt(pwd, self.actor.get_pubkey()))



@implementer(ICredentialsChecker)
class HoneypotPasswordChecker(object):
    """
    Checker that accepts "keyboard-interactive" and "password"
    """

    credentialInterfaces = (credentials.IUsernamePasswordIP,
        credentials.IPluggableAuthenticationModulesIP)

    def __init__(self, cfg):
        self.cfg = cfg

        # Are we encrypting passwords?
        self.pwcrypto = False
        if self.cfg.has_option('honeypot', 'pw_pubkey'):
            pubkey = self.cfg.get('honeypot', 'pw_pubkey')
            if len(pubkey):
                self.pwcrypto = PasswordCrypto(pubkey)


    def requestAvatarId(self, credentials):
        """
        """
        if hasattr(credentials, 'password'):
            if self.checkUserPass(credentials.username, credentials.password,
                                  credentials.ip):
                return defer.succeed(credentials.username)
            else:
                return defer.fail(UnauthorizedLogin())
        elif hasattr(credentials, 'pamConversion'):
            return self.checkPamUser(credentials.username,
                                     credentials.pamConversion, credentials.ip)
        return defer.fail(UnhandledCredentials())


    def checkPamUser(self, username, pamConversion, ip):
        """
        """
        r = pamConversion((('Password:', 1),))
        return r.addCallback(self.cbCheckPamUser, username, ip)


    def cbCheckPamUser(self, responses, username, ip):
        """
        """
        for (response, zero) in responses:
            if self.checkUserPass(username, response, ip):
                return defer.succeed(username)
        return defer.fail(UnauthorizedLogin())


    def checkUserPass(self, theusername, thepassword, ip):
        """
        """
        # UserDB is the default auth_class
        authname = auth.UserDB

        # Is the auth_class defined in the config file?
        if self.cfg.has_option('honeypot', 'auth_class'):
            authclass = self.cfg.get('honeypot', 'auth_class')
            authmodule = "cowrie.core.auth"

            # Check if authclass exists in this module
            if hasattr(modules[authmodule], authclass):
                authname = getattr(modules[authmodule], authclass)
            else:
                log.msg('auth_class: %s not found in %s' %
                    (authclass, authmodule))

        theauth = authname(self.cfg)

        if self.pwcrypto:
            enc_password = self.pwcrypto.encrypt(thepassword)
            clear_password = ""
        else:
            enc_password = ""
            clear_password = thepassword

        if theauth.checklogin(theusername, thepassword, ip):

            log.msg(eventid='cowrie.login.success',
                    format='login attempt [%(username)s/%(password)s] succeeded',
                    username=theusername.encode('string-escape'),
                    password=clear_password.encode('string-escape'),
                    encpassword=enc_password.encode('string-escape'))
            return True
        else:

            log.msg(eventid='cowrie.login.failed',
                    format='login attempt [%(username)s/%(password)s] failed',
                    username=theusername.encode('string-escape'),
                    password=clear_password.encode('string-escape'),
                    encpassword=enc_password.encode('string-escape'))
            return False

