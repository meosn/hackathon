"""Google Identity Services: locally verify ID tokens against Google's signing keys."""
import os
import jwt
from fastapi import HTTPException

keys = jwt.PyJWKClient('https://www.googleapis.com/oauth2/v3/certs', cache_keys=True, timeout=8)


def client_id():
    return os.getenv('GOOGLE_CLIENT_ID', '').strip()


def verify(credential, nonce):
    audience = client_id()
    if not audience:
        raise HTTPException(503, 'Google sign-in is not configured yet')
    try:
        key = keys.get_signing_key_from_jwt(credential).key
        claims = jwt.decode(credential, key, algorithms=['RS256'], audience=audience,
                            options={'require': ['exp', 'iat', 'iss', 'sub', 'nonce']})
        if claims['iss'] not in {'https://accounts.google.com', 'accounts.google.com'} or claims['nonce'] != nonce:
            raise jwt.InvalidTokenError('Invalid issuer or nonce')
        if claims.get('email_verified') is not True or not claims.get('email'):
            raise jwt.InvalidTokenError('Unverified email')
        return claims
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, 'Google is temporarily unavailable. Please try again.')
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, 'Google sign-in could not be verified. Please try again.')
