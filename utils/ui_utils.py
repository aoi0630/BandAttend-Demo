import re

import streamlit as st

ROLE_DISPLAY_NAMES = {
    "顧問": "先生",
}


def display_role(role):
    return ROLE_DISPLAY_NAMES.get(str(role), str(role))


def apply_mobile_style():
    st.markdown("""
    <style>
    html, body, .stApp {
        background: #F5F5F7;
    }

    .block-container {
        padding-top: 1.2rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 900px;
    }

    html, body, [class*="css"] {
        -webkit-tap-highlight-color: transparent;
    }

    section[data-testid="stSidebar"],
    button[kind="header"] {
        display: none;
    }

    .mobile-card {
        background-color: white;
        padding: 20px;
        border: 1px solid #E7E7EA;
        border-radius: 16px;
        box-shadow: none;
        margin-bottom: 16px;
    }

    .mobile-title {
        font-size: 17px;
        font-weight: 700;
        color: #1E2A3A;
        margin-bottom: 6px;
    }

    .mobile-value {
        font-size: 32px;
        font-weight: 800;
        color: #D4AF37;
    }

    .mobile-text {
        font-size: 15px;
        color: #333333;
        line-height: 1.6;
    }

    div.stButton > button {
        width: 100%;
        border-radius: 12px;
        min-height: 48px;
        padding: 0.76rem 1rem;
        font-weight: 850;
        border: 1px solid #E7E7EA;
        box-shadow: none;
    }

    div.stButton > button[kind="primary"] {
        background: #1C1C1E;
        border-color: #1C1C1E;
        color: #FFFFFF;
    }

    div.stButton > button:active {
        transform: translateY(1px);
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] {
        border-radius: 14px;
    }

    div[data-testid="stForm"] {
        border: 0;
        padding: 0;
    }

    div[data-testid="stMetric"] {
        background-color: white;
        padding: 16px;
        border-radius: 16px;
        border: 1px solid #E7E7EA;
        box-shadow: none;
    }

    .ba-page-hero {
        background: #FFFFFF;
        border: 1px solid #E7E7EA;
        border-radius: 18px;
        padding: 18px;
        margin-bottom: 16px;
    }

    .ba-page-kicker {
        color: #8A8A8E;
        font-size: 12px;
        font-weight: 850;
        margin-bottom: 6px;
    }

    .ba-page-title {
        color: #050505;
        font-size: 28px;
        font-weight: 950;
        line-height: 1.15;
    }

    .ba-page-subtitle {
        color: #8A8A8E;
        font-size: 13px;
        font-weight: 750;
        line-height: 1.55;
        margin-top: 6px;
    }

    .ba-pill {
        background: #F5F5F7;
        border-radius: 999px;
        color: #55555B;
        display: inline-block;
        font-size: 11px;
        font-weight: 850;
        padding: 4px 9px;
    }

    @media screen and (max-width: 768px) {
        .block-container {
            padding-left: 0.7rem;
            padding-right: 0.7rem;
        }

        h1 {
            font-size: 1.7rem !important;
        }

        h2, h3 {
            font-size: 1.2rem !important;
        }

        .mobile-card {
            padding: 18px;
            border-radius: 16px;
        }

        .mobile-value {
            font-size: 28px;
        }

        div[data-testid="column"] {
            min-width: 0;
        }
    }
    </style>
    """, unsafe_allow_html=True)


def app_page_header(title, subtitle="", kicker="BandAttend"):
    st.markdown(
        f"""
        <div class="ba-page-hero">
            <div class="ba-page-kicker">{_clean_display_text(kicker)}</div>
            <div class="ba-page-title">{_clean_display_text(title)}</div>
            <div class="ba-page-subtitle">{_clean_display_text(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _clean_display_text(value):
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def mobile_card(title, value=None, text=None):
    with st.container(border=True):
        st.markdown(f"**{_clean_display_text(title)}**")

        if value is not None:
            st.markdown(f"### {_clean_display_text(value)}")

        if text is not None:
            lines = [
                line.strip()
                for line in _clean_display_text(text).splitlines()
                if line.strip()
            ]
            for line in lines:
                st.caption(line)
