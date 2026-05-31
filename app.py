# bot.py
import asyncio
import logging
import json
import os

from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.session.aiohttp import AiohttpSession

# =============================================
# CONFIG
# =============================================

API_TOKEN = "8830244772:AAHIbonQJmbqXKW128oSV93zS_N3A3_tXts"
ADMIN_IDS = [8670439397]
DB_FILE = "database.json"
BANNER_FILE = "banner.jpg"
PRODUCTS_PER_PAGE = 8

PAYMENT_METHODS = {
    "SOL": "Gfi4nJuQe6BQZnbq56RPGPxQeqBznbSPpeHF4gFpwnor",
    "PayPal": "saifge"
}

logging.basicConfig(level=logging.INFO)

# =============================================
# BOT INIT
# =============================================

def create_bot(proxy=None):
    if proxy:
        session = AiohttpSession(proxy=proxy)
        return Bot(token=API_TOKEN, session=session)
    return Bot(token=API_TOKEN)

bot = create_bot()
dp = Dispatcher(storage=MemoryStorage())

# =============================================
# FSM
# =============================================

class Form(StatesGroup):
    waiting_for_stock_lines_culture = State()
    waiting_for_banner = State()

# =============================================
# DATABASE
# =============================================

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "users": {},
        "orders": [],
        "maintenance": False,
        "pending_deposits": {},
        "culture_95": {}
    }

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

db = load_db()

for key in ["pending_deposits", "culture_95"]:
    if key not in db:
        db[key] = {}
        save_db(db)

# =============================================
# USERS
# =============================================

def get_user(uid: str):
    if uid not in db["users"]:
        db["users"][uid] = {"balance": 0, "orders": 0, "total_spent": 0}
        save_db(db)
    return db["users"][uid]

# =============================================
# MAINTENANCE CHECK
# =============================================

def is_blocked(user_id: int) -> bool:
    return db.get("maintenance", False) and user_id not in ADMIN_IDS

# =============================================
# SAFE EDIT
# =============================================

async def safe_edit(call, text, kb=None):
    try:
        if call.message.photo:
            await call.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await call.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass

# =============================================
# MAIN MENU
# =============================================

def main_menu(user_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎓 PassCulture -95%", callback_data="passculture")
    )
    builder.row(
        InlineKeyboardButton(text="💸 Recharger", callback_data="wallet_main"),
        InlineKeyboardButton(text="🚀 Canal", url="https://t.me/+OTJjEH_Wf6FhMjZl")
    )
    return builder.as_markup()

# =============================================
# HOME
# =============================================

async def send_home(target, user_id: int):
    uid = str(user_id)
    user = get_user(uid)

    txt = (
        f"🔥 <b>Bienvenue sur Sunrise AutoShop</b>\n"
        f"👑 #1 Vente de PassCulture\n\n"
        f"🎓 PassCulture -95%\n\n"
        f"🔒 ID : <code>{user_id}</code>\n"
        f"💸 Solde : <code>{user['balance']}€</code>\n"
        f"🔔 Support : @hassannate"
    )

    kb = main_menu(user_id)
    banner_exists = os.path.exists(BANNER_FILE)

    if isinstance(target, types.CallbackQuery):
        try:
            if banner_exists:
                media = types.InputMediaPhoto(
                    media=FSInputFile(BANNER_FILE),
                    caption=txt,
                    parse_mode="HTML"
                )
                await target.message.edit_media(media=media, reply_markup=kb)
            else:
                await safe_edit(target, txt, kb)
        except TelegramBadRequest:
            await safe_edit(target, txt, kb)
    else:
        if banner_exists:
            await target.answer_photo(FSInputFile(BANNER_FILE), caption=txt, reply_markup=kb, parse_mode="HTML")
        else:
            await target.answer(txt, reply_markup=kb, parse_mode="HTML")

# =============================================
# HANDLERS - START
# =============================================

@dp.message(Command("start"))
async def start(message: types.Message):
    if is_blocked(message.from_user.id):
        await message.answer("🔴 Le bot est en maintenance. Revenez plus tard.")
        return
    get_user(str(message.from_user.id))
    await send_home(message, message.from_user.id)

@dp.callback_query(F.data == "home")
async def back_home(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if is_blocked(call.from_user.id):
        await call.answer("🔴 Maintenance en cours.", show_alert=True)
        return
    await send_home(call, call.from_user.id)

# =============================================
# SHOP — PassCulture (bouton principal)
# =============================================

@dp.callback_query(F.data == "passculture")
async def passculture_main(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)

    products = db["culture_95"]
    has_stock = any(len(p.get("stock_items", [])) > 0 for p in products.values())

    if not products or not has_stock:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
        return await safe_edit(
            call,
            "❌ <b>Aucun produit disponible, revenez plus tard.</b>",
            builder.as_markup()
        )

    # Du stock dispo → on affiche la boutique avec pagination
    page = 0
    product_list = [(name, prod) for name, prod in products.items() if len(prod.get("stock_items", [])) > 0]
    total_pages = (len(product_list) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    
    start_idx = page * PRODUCTS_PER_PAGE
    end_idx = start_idx + PRODUCTS_PER_PAGE
    current_products = product_list[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for prod_name, prod in current_products:
        stock = len(prod.get("stock_items", []))
        price = prod['price']
        original = prod.get('original_price', price * 2)
        label = f"💳 {original:.2f}€ → {price:.2f}€"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"buy_culture_95_{prod_name}"))

    # Boutons de navigation
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Précédent", callback_data=f"page_passculture_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="page_info"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Suivant ➡️", callback_data=f"page_passculture_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)
    
    builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
    await safe_edit(call, "🎓 <b>Culture -95%</b>\n\nSélectionnez votre carte :", builder.as_markup())

# =============================================
# SHOP — Culture -95%
# =============================================

@dp.callback_query(F.data == "culture_95")
async def culture_95_shop(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)

    products = db["culture_95"]
    builder = InlineKeyboardBuilder()

    if not products:
        builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
        return await safe_edit(call, "❌ <b>Aucun produit disponible pour le moment.</b>", builder.as_markup())

    # Affichage avec pagination
    page = 0
    product_list = list(products.items())
    total_pages = (len(product_list) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    
    start_idx = page * PRODUCTS_PER_PAGE
    end_idx = start_idx + PRODUCTS_PER_PAGE
    current_products = product_list[start_idx:end_idx]

    for prod_name, prod in current_products:
        stock = len(prod.get("stock_items", []))
        price = prod['price']
        original = prod.get('original_price', price * 2)
        if stock > 0:
            label = f"💳 {original:.2f}€ → {price:.2f}€"
        else:
            label = f"❌ {original:.2f}€ → {price:.2f}€ (rupture)"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"buy_culture_95_{prod_name}"))

    # Boutons de navigation
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Précédent", callback_data=f"page_culture_95_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="page_info"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Suivant ➡️", callback_data=f"page_culture_95_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)

    builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
    await safe_edit(call, "🎓 <b>Culture -95%</b>\n\nSélectionnez votre carte :", builder.as_markup())

# =============================================
# PAGINATION PASSCULTURE
# =============================================

@dp.callback_query(F.data.startswith("page_passculture_"))
async def page_passculture(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)
    
    page = int(call.data.split("_")[-1])
    products = db["culture_95"]
    product_list = [(name, prod) for name, prod in products.items() if len(prod.get("stock_items", [])) > 0]
    total_pages = (len(product_list) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    
    if page < 0 or page >= total_pages:
        return await call.answer("❌ Page invalide", show_alert=True)
    
    start_idx = page * PRODUCTS_PER_PAGE
    end_idx = start_idx + PRODUCTS_PER_PAGE
    current_products = product_list[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for prod_name, prod in current_products:
        stock = len(prod.get("stock_items", []))
        price = prod['price']
        original = prod.get('original_price', price * 2)
        label = f"💳 {original:.2f}€ → {price:.2f}€"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"buy_culture_95_{prod_name}"))

    # Boutons de navigation
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Précédent", callback_data=f"page_passculture_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="page_info"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Suivant ➡️", callback_data=f"page_passculture_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)
    
    builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
    await safe_edit(call, "🎓 <b>Culture -95%</b>\n\nSélectionnez votre carte :", builder.as_markup())

# =============================================
# PAGINATION CULTURE 95
# =============================================

@dp.callback_query(F.data.startswith("page_culture_95_"))
async def page_culture_95(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)
    
    page = int(call.data.split("_")[-1])
    products = db["culture_95"]
    product_list = list(products.items())
    total_pages = (len(product_list) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    
    if page < 0 or page >= total_pages:
        return await call.answer("❌ Page invalide", show_alert=True)
    
    start_idx = page * PRODUCTS_PER_PAGE
    end_idx = start_idx + PRODUCTS_PER_PAGE
    current_products = product_list[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for prod_name, prod in current_products:
        stock = len(prod.get("stock_items", []))
        price = prod['price']
        original = prod.get('original_price', price * 2)
        if stock > 0:
            label = f"💳 {original:.2f}€ → {price:.2f}€"
        else:
            label = f"❌ {original:.2f}€ → {price:.2f}€ (rupture)"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"buy_culture_95_{prod_name}"))

    # Boutons de navigation
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Précédent", callback_data=f"page_culture_95_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="page_info"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Suivant ➡️", callback_data=f"page_culture_95_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)

    builder.row(InlineKeyboardButton(text="🏪 Retour", callback_data="home"))
    await safe_edit(call, "🎓 <b>Culture -95%</b>\n\nSélectionnez votre carte :", builder.as_markup())

@dp.callback_query(F.data == "page_info")
async def page_info(call: types.CallbackQuery):
    await call.answer("📄 Pagination", show_alert=True)

# =============================================
# SHOP — Achat Culture -95%
# =============================================

@dp.callback_query(F.data.startswith("buy_culture_95_"))
async def buy_culture_95(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)

    prod_name = call.data[len("buy_culture_95_"):]
    product = db["culture_95"].get(prod_name)
    if not product:
        return await call.answer("❌ Produit introuvable.", show_alert=True)

    uid = str(call.from_user.id)
    user = get_user(uid)
    price = product["price"]
    stock_items = product.get("stock_items", [])

    if len(stock_items) == 0:
        return await call.answer("❌ Rupture de stock", show_alert=True)
    if user["balance"] < price:
        return await call.answer("❌ Solde insuffisant", show_alert=True)

    item_delivered = stock_items.pop(0)
    user["balance"] -= price
    user["orders"] += 1
    user["total_spent"] += price

    db["orders"].append({
        "uid": uid,
        "product": prod_name,
        "category": "culture_95",
        "price": price,
        "date": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db)

    await call.answer(f"✅ Achat confirmé : {prod_name}", show_alert=True)

    try:
        await bot.send_message(
            chat_id=call.from_user.id,
            text=(
                f"✅ <b>Achat réussi — {prod_name}</b>\n\n"
                f"🎁 Votre produit :\n<code>{item_delivered}</code>\n\n"
                f"💰 Prix : <code>{price}€</code>\n"
                f"💳 Nouveau solde : <code>{user['balance']}€</code>"
            ),
            parse_mode="HTML"
        )
    except:
        pass

    await safe_edit(
        call,
        (
            f"✅ <b>Achat réussi</b>\n\n"
            f"🎁 Produit : <code>{prod_name}</code>\n"
            f"💰 Prix : <code>{price}€</code>\n"
            f"💳 Nouveau solde : <code>{user['balance']}€</code>\n\n"
            f"📩 Votre produit vous a été envoyé en message privé."
        ),
        main_menu(call.from_user.id)
    )

# =============================================
# WALLET
# =============================================

@dp.callback_query(F.data == "wallet_main")
async def wallet(call: types.CallbackQuery):
    if is_blocked(call.from_user.id):
        return await call.answer("🔴 Maintenance en cours.", show_alert=True)

    uid = str(call.from_user.id)
    user = get_user(uid)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="home"))

    txt = (
        f"💳 <b>WALLET</b>\n\n"
        f"💰 Solde : <code>{user['balance']}€</code>\n"
        f"📊 Dépensé : <code>{user['total_spent']}€</code>\n\n"
        f"💸 <b>Pour recharger :</b>\n"
        f"Contactez l'admin @hassannate en DM avec :\n"
        f"- Le montant en €\n"
        f"- La méthode de paiement (SOL ou PayPal)"
    )
    await safe_edit(call, txt, builder.as_markup())

# =============================================
# ADMIN - ACCEPTER / REFUSER DÉPÔT
# =============================================

@dp.callback_query(F.data.startswith("dep_accept_"))
async def accept_deposit(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    deposit_id = call.data[len("dep_accept_"):]
    dep = db["pending_deposits"].get(deposit_id)

    if not dep:
        return await call.answer("❌ Dépôt introuvable.", show_alert=True)
    if dep["status"] != "pending":
        return await call.answer("⚠️ Déjà traité.", show_alert=True)

    uid = dep["uid"]
    amount = dep["amount"]
    user = get_user(uid)
    user["balance"] += amount
    dep["status"] = "accepted"
    save_db(db)

    await call.answer(f"✅ +{amount}€ crédité à {uid}", show_alert=True)
    try:
        await call.message.edit_caption(caption=call.message.caption + "\n\n✅ <b>ACCEPTÉ</b>", parse_mode="HTML")
    except:
        pass
    try:
        await bot.send_message(
            chat_id=int(uid),
            text=f"✅ <b>Recharge acceptée !</b>\n\n💰 <code>{amount}€</code> ont été ajoutés à votre solde.",
            parse_mode="HTML"
        )
    except:
        pass

@dp.callback_query(F.data.startswith("dep_refuse_"))
async def refuse_deposit(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    deposit_id = call.data[len("dep_refuse_"):]
    dep = db["pending_deposits"].get(deposit_id)

    if not dep:
        return await call.answer("❌ Dépôt introuvable.", show_alert=True)
    if dep["status"] != "pending":
        return await call.answer("⚠️ Déjà traité.", show_alert=True)

    uid = dep["uid"]
    amount = dep["amount"]
    dep["status"] = "refused"
    save_db(db)

    await call.answer("❌ Dépôt refusé.", show_alert=True)
    try:
        await call.message.edit_caption(caption=call.message.caption + "\n\n❌ <b>REFUSÉ</b>", parse_mode="HTML")
    except:
        pass
    try:
        await bot.send_message(
            chat_id=int(uid),
            text=f"❌ <b>Recharge refusée.</b>\n\nVotre demande de <code>{amount}€</code> a été refusée. Contactez un admin si c'est une erreur.",
            parse_mode="HTML"
        )
    except:
        pass

# =============================================
# ADMIN PANEL
# =============================================

async def show_admin_panel(target, is_message=False):
    maint = db.get("maintenance", False)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats"),
        InlineKeyboardButton(text="🖼 Bannière", callback_data="admin_banner")
    )
    builder.row(
        InlineKeyboardButton(
            text=f"{'🟢 Maintenance ON' if maint else '🔴 Mettre en maintenance'}",
            callback_data="admin_toggle_maintenance"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🎓 Culture -95%", callback_data="admin_culture_95")
    )
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="home"))

    txt = (
        f"🔧 <b>Panel Admin</b>\n\n"
        f"👥 Utilisateurs : <code>{len(db['users'])}</code>\n"
        f"📦 Commandes : <code>{len(db['orders'])}</code>\n"
        f"⚙️ Maintenance : <code>{'ON' if maint else 'OFF'}</code>"
    )

    if is_message:
        await target.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await safe_edit(target, txt, builder.as_markup())

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ Pas autorisé")
    await show_admin_panel(message, is_message=True)

@dp.message(Command("add"))
async def add_balance_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ Pas autorisé")
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("❌ Usage: /add montant id\nExemple: /add 50 123456789")
        
        amount = float(parts[1])
        user_id = parts[2]
        
        if amount <= 0:
            return await message.answer("❌ Le montant doit être positif")
        
        user = get_user(user_id)
        user["balance"] += amount
        save_db(db)
        
        await message.answer(
            f"✅ <b>Balance ajoutée</b>\n\n"
            f"👤 ID : <code>{user_id}</code>\n"
            f"💰 Montant : <code>{amount}€</code>\n"
            f"💳 Nouveau solde : <code>{user['balance']}€</code>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ Montant invalide. Usage: /add montant id\nExemple: /add 50 123456789")

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_cb(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    await show_admin_panel(call)

# =============================================
# ADMIN - MAINTENANCE
# =============================================

@dp.callback_query(F.data == "admin_toggle_maintenance")
async def toggle_maintenance(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    db["maintenance"] = not db.get("maintenance", False)
    save_db(db)
    status = "activée 🔴" if db["maintenance"] else "désactivée 🟢"
    await call.answer(f"Maintenance {status}", show_alert=True)
    await show_admin_panel(call)

# =============================================
# ADMIN - STATS
# =============================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    revenue = sum(o["price"] for o in db["orders"])
    pending = sum(1 for d in db.get("pending_deposits", {}).values() if d["status"] == "pending")

    txt = (
        f"📊 <b>Statistiques</b>\n\n"
        f"👥 Utilisateurs : <code>{len(db['users'])}</code>\n"
        f"📦 Commandes : <code>{len(db['orders'])}</code>\n"
        f"💰 Revenus : <code>{revenue}€</code>\n"
        f"⏳ Dépôts en attente : <code>{pending}</code>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="admin_panel"))
    await safe_edit(call, txt, builder.as_markup())

# =============================================
# ADMIN - BANNIÈRE
# =============================================

@dp.callback_query(F.data == "admin_banner")
async def admin_banner(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return

    builder = InlineKeyboardBuilder()
    if os.path.exists(BANNER_FILE):
        builder.row(InlineKeyboardButton(text="🗑 Supprimer la bannière", callback_data="admin_delete_banner"))
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="admin_panel"))

    await safe_edit(call, "🖼 <b>Bannière</b>\n\nEnvoyez une image pour définir la bannière d'accueil.", builder.as_markup())
    await state.set_state(Form.waiting_for_banner)

@dp.message(Form.waiting_for_banner, F.photo)
async def receive_banner(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, BANNER_FILE)
    await message.answer("✅ Bannière mise à jour avec succès !")
    await state.clear()

@dp.callback_query(F.data == "admin_delete_banner")
async def delete_banner(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    if os.path.exists(BANNER_FILE):
        os.remove(BANNER_FILE)
        await call.answer("🗑 Bannière supprimée.", show_alert=True)
    else:
        await call.answer("Aucune bannière à supprimer.", show_alert=True)
    await state.clear()
    await show_admin_panel(call)

# =============================================
# ADMIN - Gestion Culture -95%
# =============================================

@dp.callback_query(F.data == "admin_culture_95")
async def admin_culture_95(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    builder = InlineKeyboardBuilder()
    for prod_name, prod in db["culture_95"].items():
        stock = len(prod.get("stock_items", []))
        original = prod.get('original_price', prod['price'] * 2)
        builder.row(
            InlineKeyboardButton(
                text=f"📦 {original:.2f}€ → {prod['price']:.2f}€ (stock: {stock})",
                callback_data=f"admin_prod_culture_{prod_name}"
            )
        )
    builder.row(InlineKeyboardButton(text="➕ Nouveau produit", callback_data="admin_new_prod_culture"))
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="admin_panel"))
    await safe_edit(call, "🎓 <b>Gestion Culture -95%</b>\n\n1 ligne = 1 stock", builder.as_markup())

@dp.callback_query(F.data.startswith("admin_prod_culture_"))
async def admin_prod_culture_detail(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    prod_name = call.data[len("admin_prod_culture_"):]
    prod = db["culture_95"].get(prod_name)
    if not prod:
        return await call.answer("❌ Produit introuvable.", show_alert=True)

    stock = len(prod.get("stock_items", []))
    original = prod.get('original_price', prod['price'] * 2)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Ajouter du stock", callback_data=f"admin_addstock_culture_{prod_name}"))
    builder.row(InlineKeyboardButton(text="🗑 Supprimer le produit", callback_data=f"admin_delprod_culture_{prod_name}"))
    builder.row(InlineKeyboardButton(text="⬅️ Retour", callback_data="admin_culture_95"))

    await safe_edit(
        call,
        f"📦 <b>{prod_name}</b>\n💰 Prix affiché : <code>{original:.2f}€ → {prod['price']:.2f}€</code>\n📊 Stock : <code>{stock}</code> valeur(s)",
        builder.as_markup()
    )

@dp.callback_query(F.data.startswith("admin_addstock_culture_"))
async def admin_addstock_culture(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    prod_name = call.data[len("admin_addstock_culture_"):]
    await state.update_data(prod_name=prod_name)
    await safe_edit(
        call,
        f"📦 <b>Ajouter du stock — {prod_name}</b>\n\nEnvoyez un fichier .txt OU les valeurs, <b>1 ligne = 1 stock</b> :\n\n<code>valeur1\nvaleur2\nvaleur3</code>",
        None
    )
    await state.set_state(Form.waiting_for_stock_lines_culture)

@dp.message(Form.waiting_for_stock_lines_culture)
async def receive_stock_lines_culture(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    prod_name = data["prod_name"]

    lines = []
    
    # Si c'est un fichier .txt
    if message.document:
        file = await bot.get_file(message.document.file_id)
        if not message.document.file_name.endswith('.txt'):
            await message.answer("❌ Veuillez envoyer un fichier .txt")
            return
        
        file_path = file.file_path
        await bot.download_file(file_path, "temp.txt")
        
        with open("temp.txt", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        
        os.remove("temp.txt")
    else:
        # Si c'est du texte
        lines = [l.strip() for l in message.text.strip().splitlines() if l.strip()]
    
    if not lines:
        await message.answer("❌ Aucune valeur détectée. Envoyez au moins 1 ligne.")
        return

    # Si c'est un nouveau lot, créer des produits automatiquement
    if prod_name == "NEW_BATCH":
        created_count = 0
        for i, line in enumerate(lines):
            if "Solde:" in line:
                try:
                    solde_part = line.split("Solde:")[1].split("|")[0].strip()
                    solde = float(solde_part)
                    price = solde * 0.05
                    # Créer un nom unique pour le produit
                    new_prod_name = f"Carte_{int(datetime.now().timestamp())}_{i}"
                    db["culture_95"][new_prod_name] = {
                        "price": price,
                        "original_price": solde,
                        "stock_items": [line]
                    }
                    created_count += 1
                except (ValueError, IndexError):
                    pass
        save_db(db)
        await message.answer(
            f"✅ <b>{created_count} produit(s) créé(s)</b>\n\n"
            f"Chaque ligne avec Solde: a créé un produit automatiquement.",
            parse_mode="HTML"
        )
        await state.clear()
        return

    # Sinon, ajouter au produit existant
    prod = db["culture_95"].get(prod_name)
    if not prod:
        await message.answer("❌ Produit introuvable.")
        await state.clear()
        return

    # Parser chaque ligne pour extraire le solde et calculer le prix à -95%
    added_count = 0
    for line in lines:
        # Chercher "Solde:" dans la ligne
        if "Solde:" in line:
            try:
                # Extraire la valeur après "Solde:"
                solde_part = line.split("Solde:")[1].split("|")[0].strip()
                solde = float(solde_part)
                # Calculer -95% (donc 5% du prix original)
                price = solde * 0.05
                # Mettre à jour le prix du produit
                prod["price"] = price
                prod["original_price"] = solde
                # Ajouter la ligne au stock
                prod["stock_items"].append(line)
                added_count += 1
            except (ValueError, IndexError):
                # Si le parsing échoue, on ajoute quand même la ligne
                prod["stock_items"].append(line)
                added_count += 1
        else:
            # Si pas de Solde:, on ajoute la ligne telle quelle
            prod["stock_items"].append(line)
            added_count += 1
    
    save_db(db)

    await message.answer(
        f"✅ <b>{added_count} valeur(s) ajoutée(s)</b> au stock de <i>{prod_name}</i>\n"
        f"📊 Stock total : <code>{len(prod['stock_items'])}</code>\n"
        f"💰 Prix : <code>{prod.get('original_price', 0):.2f}€ → {prod['price']:.2f}€</code>",
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data.startswith("admin_delprod_culture_"))
async def admin_delprod_culture(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    prod_name = call.data[len("admin_delprod_culture_"):]
    if prod_name in db["culture_95"]:
        del db["culture_95"][prod_name]
        save_db(db)
        await call.answer(f"🗑 {prod_name} supprimé.", show_alert=True)
    await show_admin_panel(call)

@dp.callback_query(F.data == "admin_new_prod_culture")
async def admin_new_prod_culture(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await safe_edit(
        call, 
        "📦 <b>Ajouter des produits en lot</b>\n\n"
        "Envoyez un fichier .txt OU collez les lignes complètes (1 ligne = 1 produit) :\n\n"
        "<code>bibisecours@gmail.com:Haribo67880$| Prenom: BIXENTE | Nom: BEYLER | Solde:300 | Dob:2005-08-16</code>\n\n"
        "Le bot va automatiquement :\n"
        "- Extraire le Solde\n"
        "- Calculer le prix à -95%\n"
        "- Créer les produits",
        None
    )
    await state.set_state(Form.waiting_for_stock_lines_culture)
    await state.update_data(prod_name="NEW_BATCH")

# =============================================
# RUN
# =============================================

async def main():
    global bot

    PROXIES = [None, "http://103.152.112.162:80", "http://47.74.152.29:8888"]

    for proxy in PROXIES:
        try:
            label = proxy if proxy else "sans proxy"
            logging.info(f"Tentative de connexion {label}...")
            bot = create_bot(proxy)
            me = await bot.get_me()
            logging.info(f"✅ Connecté en tant que @{me.username} ({label})")
            await dp.start_polling(bot)
            return
        except Exception as ex:
            logging.warning(f"❌ Échec ({label}) : {ex}")
            try:
                await bot.session.close()
            except:
                pass

    logging.error("❌ Impossible de se connecter.")

if __name__ == "__main__":
    asyncio.run(main())
