try:
    import unittest2 as unittest
except ImportError:
    import unittest  # noqa

import base64
import kerberos
from mock import Mock, patch
import six
import struct

from puresasl import SASLProtocolException
from puresasl.client import SASLClient
from puresasl.mechanisms import AnonymousMechanism, PlainMechanism, GSSAPIMechanism, DigestMD5Mechanism


class _BaseMechanismTests(unittest.TestCase):

    sasl_kwargs = {}

    def setUp(self):
        self.sasl = SASLClient('localhost', mechanism=self.mechanism_class.name, **self.sasl_kwargs)
        self.mechanism = self.sasl._chosen_mech

    def test_init_basic(self, *args):
        sasl = Mock(host='localhost')
        mech = self.mechanism.__class__(sasl, ignored_prop=3, **self.sasl_kwargs)
        self.assertIs(mech.sasl, sasl)

    def test_process_basic(self, *args):
        self.assertIsInstance(self.sasl.process(six.b('string')), six.binary_type)
        self.assertIsInstance(self.sasl.process(six.b('string')), six.binary_type)

    def test_dispose_basic(self, *args):
        self.sasl.dispose()

    def test_wrap_unwrap(self, *args):
        self.assertRaises(NotImplementedError, self.sasl.wrap, 'msg')
        self.assertRaises(NotImplementedError, self.sasl.unwrap, 'msg')


class AnonymousMechanismTest(_BaseMechanismTests):

    mechanism_class = AnonymousMechanism


class PlainTextMechanismTest(_BaseMechanismTests):

    mechanism_class = PlainMechanism
    username = 'user'
    password = 'pass'
    sasl_kwargs = {'username': username, 'password': password}

    def test_process(self):
        for challenge in (None, '', b'asdf',  u"\U0001F44D"):
            response = self.sasl.process(challenge)
            self.assertIn(self.username, response)
            self.assertIn(self.password, response)
            self.assertIsInstance(response, six.binary_type)

    def test_wrap_unwrap(self):
        msg = 'msg'
        self.assertIs(self.sasl.wrap(msg), msg)
        self.assertIs(self.sasl.unwrap(msg), msg)


@patch('puresasl.mechanisms.kerberos.authGSSClientStep')
@patch('puresasl.mechanisms.kerberos.authGSSClientResponse', return_value=base64.b64encode('some\x00 response'))
class GSSAPIMechanismTest(_BaseMechanismTests):

    mechanism_class = GSSAPIMechanism
    service = 'GSSAPI'
    sasl_kwargs = {'service': service}


    @patch('puresasl.mechanisms.kerberos.authGSSClientWrap')
    @patch('puresasl.mechanisms.kerberos.authGSSClientUnwrap')
    def test_wrap_unwrap(self, _inner1, _inner2, authGSSClientResponse, *args):
        # bypassing process setup by setting qop directly
        self.mechanism.qop = 'auth'
        msg = b'msg'
        self.assertIs(self.sasl.wrap(msg), msg)
        self.assertIs(self.sasl.unwrap(msg), msg)

        for qop in ('auth-int', 'auth-conf'):
            self.mechanism.qop = qop
            with patch('puresasl.mechanisms.kerberos.authGSSClientResponseConf', return_value=1):
                self.assertEqual(self.sasl.wrap(msg), base64.b64decode(authGSSClientResponse.return_value))
                self.assertEqual(self.sasl.unwrap(msg), base64.b64decode(authGSSClientResponse.return_value))
            if qop == 'auth-conf':
                with patch('puresasl.mechanisms.kerberos.authGSSClientResponseConf', return_value=0):
                    self.assertRaises(StandardError, self.sasl.unwrap, msg)

    def test_process_no_user(self, authGSSClientResponse, *args):
        msg = 'whatever'

        # no user
        self.assertEqual(self.sasl.process(msg), base64.b64decode(authGSSClientResponse.return_value))
        with patch('puresasl.mechanisms.kerberos.authGSSClientResponse', return_value=six.b('')):
            self.assertEqual(self.sasl.process(msg), six.b(''))

        username = 'username'
        # user; this has to be last because it sets mechanism.user
        with patch('puresasl.mechanisms.kerberos.authGSSClientStep', return_value=kerberos.AUTH_GSS_COMPLETE),\
                patch('puresasl.mechanisms.kerberos.authGSSClientUserName', return_value=six.b(username)):
            self.assertEqual(self.sasl.process(msg), six.b(''))
            self.assertEqual(self.mechanism.user, username)

    @patch('puresasl.mechanisms.kerberos.authGSSClientUnwrap')
    def test_process_qop(self, *args):
        self.mechanism._have_negotiated_details = True
        self.mechanism.user = 'user'
        msg = six.b('msg')
        # default patch returns an invalid response for this phase
        self.assertRaises(SASLProtocolException, self.sasl.process, msg)

        max_len = 100
        for i, qop in ((1, 'auth'), (2, 'auth-int'), (4, 'auth-conf')):  # 1, 2, 4 --> qop flag
            qop_size = struct.pack('!i', i << 24 | 100)
            response = base64.b64encode(qop_size)
            with patch('puresasl.mechanisms.kerberos.authGSSClientResponse', return_value=response), \
                    patch('puresasl.mechanisms.kerberos.authGSSClientWrap') as authGSSClientWrap:
                self.mechanism.complete = False
                self.assertEqual(self.sasl.process(msg), qop_size)
                self.assertTrue(self.mechanism.complete)
                self.assertEqual(self.mechanism.qop, qop)

                args = authGSSClientWrap.call_args[0]
                out_data = args[1]
                out = base64.b64decode(out_data)
                self.assertEqual(out[:4], qop_size)
                self.assertEqual(out[4:], self.mechanism.user)



class DigestMD5MechanismTest(unittest.TestCase):

    def test_not_implemented(self):
        self.assertRaises(NotImplementedError, SASLClient, 'localhost', mechanism=DigestMD5Mechanism.name)