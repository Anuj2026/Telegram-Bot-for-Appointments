import os
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = 1817805836

# ====== GOOGLE SHEETS SETUP ======
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
CLIENT = gspread.authorize(CREDS)
SHEET = CLIENT.open("Appointments").sheet1  # Change to your sheet name

# ====== TEMPORARY BOOKING STORAGE ======
user_booking_data = {}

# ====== START ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(" About", callback_data="about")],
        [InlineKeyboardButton("📅 Book an Appointment", callback_data="appointment")]
    ]
    await update.message.reply_text("Welcome! Please choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

# ====== ABOUT ======
async def send_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    file_path = "files/Anuj_Resume.pdf"
    if os.path.exists(file_path):
        await query.message.reply_text("Hello, I am a CS student and I have made this bot for easier appointment scheduling via telegram I hope you will like it:")
        await query.message.reply_document(document=open(file_path, "rb"))
    else:
        await query.message.reply_text("❌ Sorry, About file not found.")

# ====== GET DAYS ======
def get_week_days(start_date, exclude_past=False):
    days_buttons = []
    today = datetime.now()
    for i in range(7):
        day = start_date + timedelta(days=i)
        if day.weekday() != 6:  # No Sunday
            if exclude_past and day.date() < today.date():
                continue
            day_str = day.strftime("%A %d-%m-%y")
            days_buttons.append([InlineKeyboardButton(day_str, callback_data=f"day_{day_str}")])
    return days_buttons

# ====== BUTTON HANDLER ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()


    if query.data == "ignore":
        await query.answer("❌ This slot is already booked.", show_alert=True)
        return


    if query.data == "appointment":
        today = datetime.now()
        days_buttons = get_week_days(today, exclude_past=True)
        days_buttons.append([InlineKeyboardButton("➡ Next Week", callback_data="next_week")])
        await query.message.reply_text("📅 Choose a date (This Week):", reply_markup=InlineKeyboardMarkup(days_buttons))

    elif query.data == "next_week":
        today = datetime.now()
        days_ahead = (7 - today.weekday()) % 7
        next_week_start = today + timedelta(days=days_ahead)
        days_buttons = get_week_days(next_week_start)
        await query.message.reply_text("📅 Choose a date (Next Week):", reply_markup=InlineKeyboardMarkup(days_buttons))

    elif query.data.startswith("day_"):
        chosen_day = query.data.replace("day_", "")
        user_booking_data[query.from_user.id] = {"date": chosen_day, "user_id": query.from_user.id}

        # Default slots
        time_slots = ["10:00am–11:00am", "11:00am–12:00pm", "12:00pm–13:00pm"]

        # Remove past times if booking today
        today_str = datetime.now().strftime("%A %d-%m-%y")
        if chosen_day == today_str:
            current_hour = datetime.now().hour
            time_slots = [slot for slot in time_slots if int(slot.split(":")[0]) > current_hour]

        # --- Check booked slots from Google Sheet ---
        booked_slots = []
        all_rows = SHEET.get_all_values()
        for row in all_rows[1:]:  # Skip header
            row_date = row[2]   # Date column (index 2)
            row_time = row[3]   # Time column (index 3)
            row_status = row[4] # Status column (index 4)
            if row_date == chosen_day and row_status == "Accepted":
                booked_slots.append(row_time)

        # Build buttons
        time_buttons = []
        for slot in time_slots:
            if slot in booked_slots:
                time_buttons.append([InlineKeyboardButton(f"❌ {slot} (Booked)", callback_data="ignore")])
            else:
                time_buttons.append([InlineKeyboardButton(slot, callback_data=f"time_{slot}")])

        await query.message.reply_text(
            f"🕒 Choose a time slot for {chosen_day}:",
            reply_markup=InlineKeyboardMarkup(time_buttons)
        )


    elif query.data.startswith("time_"):
        chosen_time = query.data.replace("time_", "")
        user_booking_data[query.from_user.id]["time"] = chosen_time
        await query.message.reply_text("Please enter your name:")

# ====== NAME & CONTACT ======
async def collect_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_booking_data:
        booking = user_booking_data[user_id]

        if "name" not in booking:
            booking["name"] = update.message.text
            await update.message.reply_text("Please enter your contact number:")

        elif "contact" not in booking:
            booking["contact"] = update.message.text

            # Save booking in Google Sheet including user_id
            SHEET.append_row([
                booking["name"],
                booking["contact"],
                booking["date"],
                booking["time"],
                "Pending",
                str(booking["user_id"])  # Store user_id for later reference
            ])

            await update.message.reply_text("✅ Your appointment request has been submitted. You will be notified once confirmed.")
            print(f"New booking: {booking}")

            # Notify admin
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"📅 *New Appointment Request*\n"
                    f"👤 Name: {booking['name']}\n"
                    f"📞 Contact: {booking['contact']}\n"
                    f"📆 Date: {booking['date']}\n"
                    f"🕒 Time: {booking['time']}"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Accept", callback_data=f"admin_accept_{booking['contact']}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{booking['contact']}"),
                        InlineKeyboardButton("♻ Reschedule", callback_data=f"admin_reschedule_{booking['contact']}")
                    ]
                ])
            )

            del user_booking_data[user_id]

# ====== ADMIN ACTION ======
async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != str(ADMIN_CHAT_ID):
        await query.message.reply_text("❌ You are not authorized to perform this action.")
        return

    action, contact = query.data.split("_", 2)[1:]  # e.g. admin_accept_9876543210 → accept, 9876543210
    
    cell = SHEET.find(contact)  # Find by contact number

    if cell:
        row = cell.row
        user_id_cell = SHEET.cell(row, 6).value  # Column 6 stores user_id
        user_id = int(user_id_cell) if user_id_cell.isdigit() else None

        if action == "accept":
            # Update status in sheet
            SHEET.update_cell(row, 5, "Accepted")

            # Fetch date and time from sheet
            date_value = SHEET.cell(row, 3).value  # Column 3 = date
            time_value = SHEET.cell(row, 4).value  # Column 4 = time

            await query.message.reply_text("✅ Appointment accepted and user notified.")

            # Send confirmation to user with details
            if user_id:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"✅ Your appointment has been *accepted*.\n\n"
                        f"📆 Date: {date_value}\n"
                        f"🕒 Time: {time_value}\n"
                        f"📍 We look forward to seeing you!"
                    ),
                    parse_mode="Markdown"
                )
            print(f"Appointment accepted for {contact} on {date_value} at {time_value}")

        elif action == "reject":
            SHEET.update_cell(row, 5, "Rejected")
            await query.message.reply_text("❌ Appointment rejected and user notified.")
            if user_id:
                await context.bot.send_message(chat_id=user_id, text="❌ Your appointment request has been rejected.")

        elif action == "reschedule":
            SHEET.update_cell(row, 5, "Reschedule Requested")
            await query.message.reply_text("♻ Reschedule requested. User asked to select a new date/time.")

            if user_id:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "♻ Admin has requested you to reschedule your appointment.\n\n"
                        "📅 Please select a new date:"
                    ),
                    reply_markup=InlineKeyboardMarkup(get_week_days(datetime.now(), exclude_past=True))
                )

# ====== MAIN ======
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(send_about, pattern="^about$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_info))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()