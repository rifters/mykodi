# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file key_encoder.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * Utility for encoding new API keys with multi-layer obfuscation
 *
 ********************************************************cm*
'''

import base64
import xbmcgui
from .crewruntime import c


def encode_api_key(plaintext_key):
    """
    Encode a plaintext API key using multi-layer obfuscation.

    This uses the same encoding algorithm as keys.py _x() function:
    - Position-based rotation
    - XOR cipher with rotating key
    - Base64 transport encoding

    Args:
        plaintext_key (str): The plaintext API key to encode

    Returns:
        str: Base64-encoded obfuscated key suitable for keys.py
    """
    # Convert to bytes
    data = plaintext_key.encode('utf-8')

    # Stage 1: Apply position-based rotation
    rotated = bytearray(len(data))
    for i in range(len(data)):
        rotated[i] = ((data[i] + i) % 256)

    # Stage 2: XOR cipher with rotating key
    key = [0x54, 0x68, 0x65, 0x43, 0x72, 0x65, 0x77, 0x32, 0x30, 0x32, 0x36]  # 'TheCrew2026'
    result = bytearray()
    for i, byte in enumerate(rotated):
        result.append(byte ^ key[i % len(key)])

    # Stage 3: Base64 transport encoding
    encoded = base64.b64encode(result).decode('utf-8')

    return encoded


def decode_api_key(encoded_key):
    """
    Decode an obfuscated API key (for verification).

    This reverses the encoding process to verify the key was encoded correctly.

    Args:
        encoded_key (str): Base64-encoded obfuscated key

    Returns:
        str: Decoded plaintext API key
    """
    # Stage 1: Decode from base64
    b = base64.b64decode(encoded_key)

    # Stage 2: XOR cipher with rotating key
    key = [0x54, 0x68, 0x65, 0x43, 0x72, 0x65, 0x77, 0x32, 0x30, 0x32, 0x36]
    result = bytearray()
    for i, byte in enumerate(b):
        result.append(byte ^ key[i % len(key)])

    # Stage 3: Reverse position-based rotation
    decoded = bytes(((result[j] - j) & 0xFF) for j in range(len(result)))

    return decoded.decode('utf-8')


def show_key_encoder_dialog():
    """
    Show interactive dialog for encoding new API keys.

    This is the main entry point called from the DevTools menu.
    Allows users to:
    1. Enter a plaintext API key
    2. Get the encoded version for keys.py
    3. Copy to clipboard or view the code to add
    """
    if not c.devmode:
        c.infoDialog('Key Encoder is only available in DevMode.\n\nEnable DevMode in addon settings.', sound=True, icon='INFO')
        return

    # Show input dialog for API key
    dialog = xbmcgui.Dialog()
    plaintext = dialog.input(
        'Enter API Key to Encode',
        type=xbmcgui.INPUT_ALPHANUM
    )

    if not plaintext:
        return

    try:
        # Encode the key
        encoded = encode_api_key(plaintext)

        # Verify it decodes correctly
        decoded = decode_api_key(encoded)

        if decoded != plaintext:
            c.infoDialog('Error: Encoding verification failed!\n\nDecoded key does not match original.', sound=True, icon='ERROR')
            c.log(f'[Key Encoder] Encoding verification failed!', 1)
            c.log(f'[Key Encoder] Original: {plaintext}', 1)
            c.log(f'[Key Encoder] Decoded: {decoded}', 1)
            return

        # Show success dialog with code to add
        variable_name = dialog.input(
            'Enter variable name (e.g., my_api_key)',
            type=xbmcgui.INPUT_ALPHANUM,
            defaultt='new_api_key'
        )

        if not variable_name:
            variable_name = 'new_api_key'

        # Generate the code snippet
        code_snippet = f"{variable_name} = _x(b'{encoded}')"

        # Show result dialog with options
        result_text = (
            f'[B]API Key Encoded Successfully![/B]\n\n'
            f'[B]Original Key:[/B]\n{plaintext[:50]}{"..." if len(plaintext) > 50 else ""}\n\n'
            f'[B]Encoded Length:[/B] {len(encoded)} bytes\n'
            f'[B]Original Length:[/B] {len(plaintext)} bytes\n\n'
            f'The encoded key is ready to use in keys.py.\n'
            f'Next: You can copy the code from the text field.'
        )

        dialog.textviewer('[COLOR gold]API Key Encoder[/COLOR]', result_text)

        # Show copyable text field with the code snippet
        # User can select all (Ctrl+A) and copy (Ctrl+C) on PC
        dialog.input(
            'Copy this line to keys.py (Ctrl+A then Ctrl+C)',
            type=xbmcgui.INPUT_ALPHANUM,
            defaultt=code_snippet
        )

        # Log to Kodi log for easy copying
        c.log('=' * 80, 1)
        c.log('[Key Encoder] New API Key Encoded', 1)
        c.log('=' * 80, 1)
        c.log(f'Variable Name: {variable_name}', 1)
        c.log(f'Original Key: {plaintext}', 1)
        c.log(f'Code to add to keys.py:', 1)
        c.log(code_snippet, 1)
        c.log('=' * 80, 1)

        c.infoDialog(
            f'[OK] Key encoded successfully!\n\n'
            f'Code snippet also logged to the_crew.log\n\n'
            f'{variable_name} = _x(b\'...\')',
            sound=False,
            icon='INFO'
        )

    except Exception as e:
        c.log(f'[Key Encoder] Error encoding key: {e}', 1)
        c.infoDialog(f'Error encoding key:\n\n{str(e)}', sound=True, icon='ERROR')


def batch_encode_keys():
    """
    Batch encode multiple API keys at once.

    Shows a dialog where users can enter multiple keys (one per line)
    and get all the encoded versions at once.
    """
    if not c.devmode:
        c.infoDialog('Key Encoder is only available in DevMode.', sound=True, icon='INFO')
        return

    dialog = xbmcgui.Dialog()

    # Instructions
    dialog.ok(
        'Batch API Key Encoder',
        'Enter API keys in the following format (one per line):\n'
        'variable_name=plaintext_key\n\n'
        'Example:\n'
        'tmdb_key=0049795edb57568b95240bc9e61a9dfc\n'
        'tvdb_key=27bef29779bbffe947232dc310a91f0c'
    )

    # Get input
    input_text = dialog.input(
        'Enter keys (one per line)',
        type=xbmcgui.INPUT_ALPHANUM
    )

    if not input_text:
        return

    try:
        # Parse input (simple version - in real use would be more robust)
        lines = input_text.split('|')  # Using | as separator since newlines don't work in input dialog

        results = []
        for line in lines:
            if '=' not in line:
                continue

            var_name, key_value = line.split('=', 1)
            var_name = var_name.strip()
            key_value = key_value.strip()

            encoded = encode_api_key(key_value)
            decoded = decode_api_key(encoded)

            if decoded == key_value:
                results.append(f"{var_name} = _x(b'{encoded}')")
            else:
                results.append(f"# ERROR: {var_name} encoding failed")

        # Show results
        result_text = '\n'.join(results)
        dialog.textviewer('Encoded API Keys', result_text)

        # Log results
        c.log('=' * 80, 1)
        c.log('[Key Encoder] Batch Encoding Results', 1)
        c.log('=' * 80, 1)
        c.log(result_text, 1)
        c.log('=' * 80, 1)

        c.infoDialog(f'[OK] Encoded {len(results)} keys!\n\nCheck the_crew.log for the code.', sound=False, icon='INFO')

    except Exception as e:
        c.log(f'[Key Encoder] Batch encoding error: {e}', 1)
        c.infoDialog(f'Error in batch encoding:\n\n{str(e)}', sound=True, icon='ERROR')
