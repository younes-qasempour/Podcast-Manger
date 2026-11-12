"""
Simple & Direct Telegram Login Script
Run this script in terminal to log in directly into Telegram.
Once logged in, your session is saved to tg_podcast_session.session,
and both the GUI (python gui.py) and CLI will work immediately without asking for login again!
"""
import sys
import asyncio
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import qrcode

from config import Config

async def quick_login():
    cfg = Config()
    
    print("\n" + "=" * 60)
    print("       🎙️ TELEGRAM PODCAST MANAGER - QUICK LOGIN")
    print("=" * 60)
    
    client = TelegramClient(
        str(cfg.session_path),
        int(cfg.api_id),
        cfg.api_hash,
        device_model="Desktop",
        system_version="Windows 11",
        app_version="5.0.0"
    )
    
    print("\nConnecting to Telegram servers...")
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        user_name = (me.first_name or "") + (f" {me.last_name}" if me.last_name else "")
        print(f"\n✅ You are ALREADY LOGGED IN as: {user_name} (@{me.username or 'NoUsername'})")
        print(f"Session saved to: {cfg.session_name}.session")
        print("\n🚀 You can now close this window and launch: python gui.py")
        await client.disconnect()
        return

    print("\nChoose how you want to log in:")
    print("  [1] 📲 Instant QR Code (Scan with your Telegram mobile app) [RECOMMENDED]")
    print("  [2] 📱 Phone Number + SMS/Telegram Code")
    choice = input("\nEnter choice [1/2] (Default is 1): ").strip()
    
    if choice == "2":
        phone = input("\nEnter your phone number with country code (e.g. +989123456789): ").strip()
        if not phone:
            print("❌ Phone number cannot be empty.")
            await client.disconnect()
            return
        
        try:
            await client.start(phone=phone)
        except SessionPasswordNeededError:
            pwd = input("\n🔐 Enter your 2FA Cloud Password: ").strip()
            await client.sign_in(password=pwd)
    else:
        print("\nGenerating QR code from Telegram...")
        try:
            qr_login = await client.qr_login()
            
            print("\n" + "-" * 60)
            print("📲 SCAN WITH TELEGRAM ON YOUR PHONE:")
            print("   1. Open Telegram on your phone")
            print("   2. Go to: Settings -> Devices -> Link Desktop Device")
            print("   3. Scan this QR code with your phone camera:")
            print("-" * 60 + "\n")
            
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)
            
            print("\nWaiting for scan (up to 90 seconds)...")
            try:
                await qr_login.wait(timeout=90)
            except SessionPasswordNeededError:
                pwd = input("\n🔐 Enter your 2FA Cloud Password: ").strip()
                await client.sign_in(password=pwd)
            except asyncio.TimeoutError:
                print("\n⚠️ QR code expired.")
                fallback = input("Do you want to log in using your phone number instead? [Y/n]: ").strip().lower()
                if fallback in ("", "y", "yes"):
                    phone = input("Enter phone number (+98...): ").strip()
                    await client.start(phone=phone)
                else:
                    print("Exiting.")
                    await client.disconnect()
                    return
        except Exception as e:
            print(f"\nQR Login error: {e}")
            print("Falling back to phone login...")
            phone = input("Enter phone number (+98...): ").strip()
            await client.start(phone=phone)

    me = await client.get_me()
    user_name = (me.first_name or "") + (f" {me.last_name}" if me.last_name else "")
    print("\n" + "=" * 60)
    print(f"🎉 SUCCESS! Logged in as: {user_name} (@{me.username or 'NoUsername'})")
    print(f"Session saved permanently: {cfg.session_name}.session")
    print("=" * 60)
    print("\n🚀 Now you can launch: python gui.py")
    await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(quick_login())
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
    except Exception as err:
        print(f"\n❌ Error during login: {err}")
    input("\nPress Enter to exit...")
