import os
import logging
import google.generativeai as genai  # Updated import
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from PIL import Image


# Update constants
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_USERNAME = "@Bill_Splitting_AI_Bot"
GEMINI_API_KEY = "AIzaSyB5dTq2XK6ut9O46_ez48qBcxJe54Rn-uI"

# Initialize Gemini client with updated model
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')  # Updated model version

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Change to DEBUG level
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hi! Add me to a group, then tag me ({BOT_USERNAME}) in a message with a receipt photo to split the bill.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "How to use:\n"
        "1. Add me to your group.\n"
        "2. Take a clear photo of your receipt.\n"
        "3. Send the photo to the group with caption in this format:\n\n"
        f"{BOT_USERNAME}\n"
        "Person1: item1, item2\n"
        "Person2: item1, item2\n\n"
        "Example:\n"
        f"{BOT_USERNAME}\n"
        "Alice: burger, coke\n"
        "Bob: pasta, salad\n\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/help - This message"
    )

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    photo = message.photo[-1]
    caption = message.caption or ""
    downloaded_path = None
    
    try:
        # Extract participants info from caption
        participants_info = caption.replace(BOT_USERNAME, "").strip()
        
        if not participants_info:
            await message.reply_text("Please provide participant information in the caption!")
            return

        # Download photo
        photo_file = await photo.get_file()
        downloaded_path = await photo_file.download_to_drive()


        # Process with AI
        await message.reply_text("Processing receipt and calculating split...")
        try:
            split_result = await process_receipt_with_ai(downloaded_path, participants_info)
            # Fix escape sequence
            escaped_result = split_result.replace(".", r"\.")  # Fixed escape sequence
            await message.reply_text(
                f"🧮 *Bill Split Results:*\n```\n{escaped_result}\n```",
                parse_mode='MarkdownV2'
            )
        except Exception as api_error:
            logger.error(f"API Error: {str(api_error)}", exc_info=True)
            await message.reply_text(
                "Sorry, there was an error processing the receipt. Please try again."
            )

    except Exception as e:
        logger.error(f"Error in handle_receipt: {str(e)}", exc_info=True)
        await message.reply_text(
            "Sorry, an error occurred. Please make sure:\n"
            "1. The image is clear and readable\n"
            "2. The caption format is correct\n"
            "3. Try again or contact support if the issue persists"
        )
    finally:
        # Cleanup downloaded file
        if downloaded_path and os.path.exists(downloaded_path):
            try:
                os.remove(downloaded_path)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up file: {cleanup_error}")

async def process_receipt_with_ai(image_path: str, participants_info: str) -> str:
    try:
        # Load and process image
        image = Image.open(image_path)
        
        # Prepare prompt with more specific instructions
        prompt = f"""
        Analyze this receipt image and calculate the bill split based on the following orders:
        {participants_info}
        pay attention to quantities and prices. Be careful, some items can be shared between people. Return only final split results
        """

        response = model.generate_content(
            [prompt, image],
        )

        return response.text.strip()

    except Exception as e:
        logger.error(f"Error in process_receipt_with_ai: {str(e)}", exc_info=True)
        raise

def main() -> None:

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))


    application.add_handler(MessageHandler(
        filters.PHOTO & (filters.COMMAND | filters.ChatType.GROUPS | filters.ChatType.PRIVATE), 
        handle_receipt
    ))

    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()