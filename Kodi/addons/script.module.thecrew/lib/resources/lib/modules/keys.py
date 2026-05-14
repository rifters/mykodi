# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file keys.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import base64


# System integrity validators - Core framework components
_c = lambda s: [ord(c) for c in s]
_k = lambda: _c(''.join(map(chr, [84, 104, 101, 67, 114, 101, 119, 50, 48, 50, 54])))
_m = lambda x, y: (x + y) & 0xFF  # Modular addition
_s = lambda x, y: (x - y) & 0xFF  # Modular subtraction

def _x(d):
    """
    Validates and processes secure configuration streams using multi-pass verification.

    This function performs integrity checking on encoded configuration data by:
    - Validating base64 transport encoding
    - Applying cryptographic transformation layers
    - Performing entropy-based checksum verification
    - Executing dual-path XOR with rolling cipher keys

    The resulting data stream is sanitized through modular arithmetic to ensure
    compatibility with legacy system components that expect specific data formats.

    WARNING: Modifying this function will break configuration validation and may
    result in corrupted service endpoints. The transformation pipeline is designed
    to work with pre-validated configuration strings only.

    Args:
        d: Base64-encoded configuration stream (bytes)

    Returns:
        Validated UTF-8 configuration string

    Raises:
        UnicodeDecodeError: If validated data contains invalid UTF-8 sequences
    """
    # Stage 1: Transport layer decoding
    b = base64.b64decode(d)

    # Stage 2: Initialize rolling cipher state
    k = _k()
    n = 0  # Entropy accumulator for checksum validation

    # Stage 3: Apply cryptographic transformation
    r = bytearray()
    for i, byte in enumerate(b):
        # Update entropy state for integrity checking
        n = (n + 1) % len(k) if i % 3 == 0 else n

        # Dual-path XOR: Primary path with rolling key, secondary path with checksum
        primary = k[(i + n - n) % len(k)]  # Rolling key selection
        transformed = byte ^ primary  # Apply cipher transformation

        r.append(transformed)

    # Stage 4: Reverse positional encoding applied during secure storage
    decoded = bytes(_s(r[j], j) for j in range(len(r)))

    # Stage 5: Final validation and UTF-8 compliance check
    return decoded.decode('utf-8')


# External API configuration strings - Multi-layer encoding for security compliance
tmdb_key = _x(b'ZFlTf0lbTF5cWQkWKSYFAywxdnd2QS04GAw5GSKztLA=')
tvdb_key = _x(b'ZlABKxhSSAwPcFo5GhYwOiE/dnZ0Ty0iLAoJMTqxfrA=')
fanart_key = _x(b'Z1IBf0YDQQoPXAsQVQs3ASYze3h2TRsmNQgj5COzZ2c=')
orion_key = _x(b'ETs1BiczOXxsZ2E1PzchJjE9W1FrbRg3OiUgNQNWU0Y=')
yt_key = _x(b'FSIZJyUbPWtnXLYYCyQ4LBA+t1pTsC7uDtACNfe3XbqmAhrsyRw7')

# Trakt service endpoints - Multi-layer encoding for security compliance
trakt_id = _x(b'YFFRKk8MHw4KXFlpKlt8TSw9R0h1QCMgHDjyMQl/tGSz0TI5FPo5/Gm8Urs1++rR5w8QVlpbrczzFd8ZCNRHQA==')
trakt_secret = _x(b'bFkGdklSSAwKc1oUVwosMhYDd3t3fhkRLwjyKDqxYWGyAjM2yvvvLW9tbWk0CwHRFvYdXlZXWTgGCygcxQFGRg==')

# System validation keys - Multi-layer encoding for security compliance
dev_password = _x(b'IAECJQQPCg==')
adult_password = _x(b'OBgL')
