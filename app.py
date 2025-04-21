import os
import logging
from telegram import Update, MessageEntity, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Assume OCR function and calculation logic exist elsewhere ---
# from ocr_module import process_receipt_image
# from calculation_module import calculate_split

BOT_TOKEN = os.environ.get("7534072343:AAFjbPGd_3J7nMb4GG8rgdH8tby8d7XQYAo")
BOT_USERNAME = "@Bill_Splitting_AI_Bot" # Replace with your actual bot username

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("Hi! Add me to a group, then tag me (@YourBotName) in a message with a receipt photo to split the bill.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends help text."""
    await update.message.reply_text(
        "How to use:\n"
        "1. Add me to your group.\n"
        "2. Take a clear photo of your receipt.\n"
        "3. Send the photo to the group and **tag me in the caption** "
        f"(like this: {BOT_USERNAME} dinner receipt, Alice, Bob, Charlie participated).\n"
        "4. I will read the receipt and ask you to assign items to people.\n"
        "\nCommands:\n"
        "/start - Welcome message\n"
        "/help - This message"
    )

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles messages with photos where the bot is mentioned."""
    message = update.message
    photo = message.photo[-1] # Get the highest resolution photo
    caption = message.caption or "" # Get the caption text

    # --- Check if the bot was mentioned in the caption ---
    # Method 1: Simple string check (less robust)
    # mentioned = BOT_USERNAME in caption

    # Method 2: Check message entities (more reliable)
    mentioned = False
    if message.caption_entities:
        for entity in message.caption_entities:
            if entity.type == MessageEntity.MENTION:
                mention_text = caption[entity.offset : entity.offset + entity.length]
                if mention_text == BOT_USERNAME:
                    mentioned = True
                    break
            # You might also need to handle MessageEntity.TEXT_MENTION if users link the bot name

    if not mentioned:
        # If bot wasn't mentioned in the caption, ignore this photo message
        # (Or you could check if the photo message is a reply to a message mentioning the bot)
        logger.info("Received photo but bot wasn't mentioned in caption.")
        return

    logger.info(f"Received photo with mention from user {message.from_user.id} in chat {message.chat.id}")
    await message.reply_text("Received receipt! Processing, please wait...")

    try:
        # 1. Download the photo
        photo_file = await photo.get_file()
        downloaded_path = await photo_file.download_to_drive() # Downloads to disk
        logger.info(f"Photo downloaded to: {downloaded_path}")

        # 2. --- Call your OCR function ---
        # extracted_items = process_receipt_image(downloaded_path) # Your function here!
        # This function should return a list of items, prices, tax etc.
        # For demonstration, let's mock the response:
        extracted_items = [
            {"item": "Burger", "price": 15.00},
            {"item": "Fries", "price": 5.00},
            {"item": "Tax", "price": 1.50}
        ]
        os.remove(downloaded_path) # Clean up the downloaded file

        # --- Error handling for OCR needed here ---
        if not extracted_items:
             await message.reply_text("Sorry, I couldn't read the receipt clearly. Please try a clearer photo.")
             return

        # 3. --- Start the item assignment process ---
        # This is where you'd likely enter a ConversationHandler (more complex state management)
        # For now, just show extracted items:
        response_text = "Okay, I found these items:\n"
        for i, item_data in enumerate(extracted_items):
            response_text += f"{i+1}. {item_data['item']} - ${item_data['price']:.2f}\n"
        response_text += "\nNow, please tell me who had what..." # Start the next step here

        await message.reply_text(response_text)
        # --- TODO: Initiate ConversationHandler to ask user to assign items ---

    except Exception as e:
        logger.error(f"Error processing receipt: {e}", exc_info=True)
        await message.reply_text("Sorry, an error occurred while processing the receipt.")
        # Clean up downloaded file in case of error
        if 'downloaded_path' in locals() and os.path.exists(downloaded_path):
             os.remove(downloaded_path)


def main() -> None:
    """Start the bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Message handler for photos with mentions
    # Filters.PHOTO checks for messages containing photos
    # We add the logic *inside* handle_receipt to check for the caption mention
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_receipt))

    # --- Optional: Handler for when the bot is added to a group ---
    # You might use a ChatMemberHandler or check message.new_chat_members in a general MessageHandler

    # Start the Bot (using polling)
    logger.info("Starting bot polling...")
    application.run_polling()

if __name__ == '__main__':
    main()