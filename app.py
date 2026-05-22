import streamlit as st
import asyncio
from app.db.mongo import db

st.set_page_config(
    page_title="AI Product Catalog",
    layout="wide"
)

# ---------------- PAGE STYLES ---------------- #

st.markdown("""
<style>

.main {
    background-color: #f5f7fb;
}

.block-container {
    padding-top: 2rem;
}

.catalog-card {
    background: white;
    border-radius: 18px;
    padding: 18px;
    margin-bottom: 20px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 1px solid #ececec;
}

.product-title {
    font-size: 20px;
    font-weight: 700;
    color: #111827;
    margin-top: 10px;
}

.product-category {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 30px;
    background: #eef2ff;
    color: #4338ca;
    font-size: 12px;
    font-weight: 600;
    margin-top: 8px;
}

.info-label {
    color: #6b7280;
    font-size: 13px;
    margin-bottom: 2px;
}

.info-value {
    color: #111827;
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 12px;
}

.confidence {
    background: #ecfdf5;
    color: #047857;
    padding: 6px 12px;
    border-radius: 30px;
    font-size: 12px;
    font-weight: 700;
    display: inline-block;
}

.seller-box {
    background: #f9fafb;
    padding: 10px;
    border-radius: 12px;
    margin-top: 14px;
    border: 1px solid #e5e7eb;
}

</style>
""", unsafe_allow_html=True)

# ---------------- TITLE ---------------- #

st.title("Core Com AI Voice Product Catalog")
st.caption("AI extracted inventory from seller voice calls")

# ---------------- FETCH DATA ---------------- #

@st.cache_data(ttl=60)
def load_catalogs():
    async def _fetch():
        await db.connect()
        return await db.list_catalogs(limit=100)
    return asyncio.run(_fetch())

docs = load_catalogs()

if not docs:
    st.warning("No products available")
    st.stop()

# ---------------- CARDS ---------------- #

COLS = 3

for i in range(0, len(docs), COLS):

    cols = st.columns(COLS)

    for col, doc in zip(cols, docs[i:i+COLS]):

        product = doc.get("product", {})
        attributes = product.get("attributes", {})
        pricing = product.get("pricing", {})
        inventory = product.get("inventory", {})

        category = product.get("category") or "Unknown"
        color = attributes.get("color") or "N/A"
        material = attributes.get("material") or "N/A"
        sizes = attributes.get("size") or "N/A"
        brand = product.get("brand") or "Unbranded"
        price = pricing.get("selling_price") or "N/A"
        quantity = inventory.get("quantity") or "N/A"

        image = doc.get("image_url")

        with col:

            st.markdown('<div class="catalog-card">', unsafe_allow_html=True)

            if image:
                st.image(image, width='stretch')
            else:
                st.image(
                    "https://placehold.co/600x400?text=No+Image",
                    width='stretch'
                )

            st.markdown(
                f"<div class='product-title'>{category.title()}</div>",
                unsafe_allow_html=True
            )

            st.markdown(
                f"<div class='product-category'>{category.upper()}</div>",
                unsafe_allow_html=True
            )

            c1, c2 = st.columns(2)

            with c1:
                st.markdown(
                    "<div class='info-label'>Color</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>{color}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div class='info-label'>Price</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>₹ {price}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div class='info-label'>Brand</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>{brand}</div>",
                    unsafe_allow_html=True
                )

            with c2:

                st.markdown(
                    "<div class='info-label'>Quantity</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>{quantity}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div class='info-label'>Material</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>{material}</div>",
                    unsafe_allow_html=True
                )

                st.markdown(
                    "<div class='info-label'>Sizes</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='info-value'>{sizes}</div>",
                    unsafe_allow_html=True
                )

            st.markdown(
                f"""
                <div class='seller-box'>
                    <div class='info-label'>Seller Phone</div>
                    <div class='info-value'>{doc.get('seller_phone') or 'N/A'}</div>

                    <div class='info-label'>Language</div>
                    <div class='info-value'>{doc.get('language')}</div>

                    <div class='confidence'>
                        AI Confidence {doc.get('confidence')}%
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            with st.expander("View Transcript"):

                transcripts = doc.get("transcripts", [])

                for t in transcripts:

                    if isinstance(t, dict):
                        st.write("•", t.get("text"))
                    else:
                        st.write("•", t)

            st.markdown("</div>", unsafe_allow_html=True)