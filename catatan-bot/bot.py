import os
import re
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("Laporan Keuangan Harian").sheet1
    SHEET_OK = True
except Exception as e:
    print("Gagal konek sheet:", e)
    SHEET_OK = False


def parse_input(text):
    text = text.strip().lower()

    # deteksi tipe
    tipe = "pengeluaran"
    if "masuk" in text or "in" in text:
        tipe = "pemasukan"
        text = text.replace("masuk", "").replace("in", "").strip()

    # cari angka + satuan: 20rb, 2jt, 500k
    m = re.search(r'(\d+)\s*(rb|jt|k|juta)', text)
    if not m:
        raise ValueError("Format: item 20rb tempat [masuk]")

    angka = int(m.group(1))
    satuan = m.group(2)

    if satuan in ["jt", "juta"]:
        jumlah = angka * 1_000_000
    else: # rb, k
        jumlah = angka * 1000

    idx = m.end()
    item = text[:m.start()].strip().title()
    tempat = text[idx:].strip().title()

    if not item or not tempat:
        raise ValueError("Format: item 20rb tempat")

    return item, jumlah, tempat, tipe, f"{item} di {tempat}"

def get_df():
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    if not df.empty:
        df['Jumlah'] = df['Jumlah'].astype(int)
        df['Tanggal'] = pd.to_datetime(df['Tanggal'], format='%d/%m/%Y')
    return df

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot Keuangan Siap!\n\n"
        "Input: kopi 5rb warung\n"
        "/rekap = hari ini\n"
        "/rekapminggu = 7 hari\n"
        "/grafik = pie 7 hari\n"
        "/grafikbulan = pie 30 hari\n"
        "/export = download excel"
    )

async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SHEET_OK: return
    df = get_df()
    today = datetime.now().date()
    df_today = df[df['Tanggal'].dt.date == today]
    masuk = df_today[df_today['Tipe']=='pemasukan']['Jumlah'].sum()
    keluar = df_today[df_today['Tipe']=='pengeluaran']['Jumlah'].sum()
    await update.message.reply_text(
        f"📊 Rekap {today.strftime('%d/%m')}\n💚 Masuk: Rp{masuk:,}\n❤️ Keluar: Rp{keluar:,}\n💰 Saldo: Rp{masuk-keluar:,}".replace(",",".")
    )

async def rekap_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int):
    df = get_df()
    start_date = datetime.now().date() - timedelta(days=days-1)
    df_week = df[df['Tanggal'].dt.date >= start_date]
    masuk = df_week[df_week['Tipe']=='pemasukan']['Jumlah'].sum()
    keluar = df_week[df_week['Tipe']=='pengeluaran']['Jumlah'].sum()
    await update.message.reply_text(
        f"📊 Rekap {days} Hari\n💚 Masuk: Rp{masuk:,}\n❤️ Keluar: Rp{keluar:,}\n💰 Saldo: Rp{masuk-keluar:,}".replace(",",".")
    )

async def grafik_generic(update: Update, days: int, title: str):
    df = get_df()
    if df.empty: return await update.message.reply_text("Belum ada data")
    start_date = datetime.now() - timedelta(days=days-1)
    df_out = df[(df['Tanggal'] >= pd.Timestamp(start_date)) & (df['Tipe']=='pengeluaran')]
    if df_out.empty: return await update.message.reply_text(f"Belum ada pengeluaran {days} hari terakhir")
    grouped = df_out.groupby('Tempat')['Jumlah'].sum().nlargest(8)
    
    plt.figure(figsize=(7,7))
    grouped.plot.pie(autopct='%1.1f%%', startangle=90)
    plt.title(title)
    plt.ylabel('')
    plt.tight_layout()
    plt.savefig('grafik.png')
    plt.close()
    await update.message.reply_photo(photo=open('grafik.png','rb'))
    os.remove('grafik.png')

async def grafik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await grafik_generic(update, 7, "Pengeluaran 7 Hari Terakhir")

async def grafikbulan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await grafik_generic(update, 30, "Pengeluaran 30 Hari Terakhir")

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SHEET_OK: return
    df = get_df()
    filename = f"rekap_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df.to_excel(filename, index=False)
    await update.message.reply_document(document=InputFile(filename))
    os.remove(filename)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SHEET_OK: return await update.message.reply_text("❌ Sheet error")
    user, now = update.effective_user, datetime.now()
    success, failed = [], []
    for inp in update.message.text.split(","):
        try:
            item, jumlah, tempat, tipe, desc = parse_input(inp)
            sheet.append_row([now.strftime("%d/%m/%Y"), now.strftime("%H:%M"),
                user.full_name, user.id, tipe, item, jumlah, tempat, desc])
            success.append(f"{item} Rp{jumlah:,}")
        except: failed.append(inp.strip())
    msg = ""
    if success: msg += "✅ " + "\n".join(success)
    if failed: msg += "\n\n❌ Gagal: " + ", ".join(failed)
    await update.message.reply_text(msg)

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rekap", rekap))
    app.add_handler(CommandHandler("rekapminggu", lambda u,c: rekap_generic(u,c,7)))
    app.add_handler(CommandHandler("grafik", grafik))
    app.add_handler(CommandHandler("grafikbulan", grafikbulan))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Bot jalan...")
    app.run_polling()

if __name__ == "__main__":
    main()