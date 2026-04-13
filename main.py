import streamlit as st
import pandas as pd
import re
import io
import os
from collections import Counter
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import plotly.express as px
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import matplotlib

# ──────────────────────────────────────────────
# 한글 폰트 경로 설정 (핵심 수정 부분)
# ──────────────────────────────────────────────
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "NanumGothic-Regular (1).ttf")

# matplotlib 한글 폰트 설정
if os.path.exists(FONT_PATH):
    from matplotlib import font_manager
    font_manager.fontManager.addfont(FONT_PATH)
    font_prop = font_manager.FontProperties(fname=FONT_PATH)
    matplotlib.rcParams['font.family'] = font_prop.get_name()
else:
    matplotlib.rcParams['font.family'] = 'DejaVu Sans'

matplotlib.rcParams['axes.unicode_minus'] = False

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="유튜브 댓글 분석기",
    page_icon="📺",
    layout="wide",
)

# ──────────────────────────────────────────────
# CSS 스타일
# ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.4rem;
        font-weight: 700;
        color: #FF0000;
        text-align: center;
        margin-bottom: 0.3rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .comment-box {
        background-color: #f9f9f9;
        border-left: 4px solid #FF0000;
        padding: 12px 16px;
        margin-bottom: 10px;
        border-radius: 4px;
    }
    .comment-author { font-weight: 700; color: #333; }
    .comment-text { color: #555; line-height: 1.6; margin: 4px 0; }
    .comment-meta { color: #999; font-size: 0.85rem; }
    .reply-box {
        background-color: #f0f0f0;
        border-left: 4px solid #4285F4;
        padding: 10px 14px;
        margin: 6px 0 6px 24px;
        border-radius: 4px;
    }
    .positive { color: #28a745; font-weight: 600; }
    .negative { color: #dc3545; font-weight: 600; }
    .neutral  { color: #6c757d; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">📺 유튜브 댓글 분석기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">댓글 수집 · 감성 분석 · 워드클라우드 · 통계까지 한번에</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# 유틸리티 함수들
# ──────────────────────────────────────────────
def get_api_key():
    try:
        return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        return None


def extract_video_id(url):
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_video_info(youtube, video_id):
    try:
        resp = youtube.videos().list(part="snippet,statistics", id=video_id).execute()
        if not resp["items"]:
            return None
        item = resp["items"][0]
        s = item["snippet"]
        t = item["statistics"]
        return {
            "title": s.get("title", ""),
            "channel": s.get("channelTitle", ""),
            "published": s.get("publishedAt", "")[:10],
            "views": int(t.get("viewCount", 0)),
            "likes": int(t.get("likeCount", 0)),
            "comment_count": int(t.get("commentCount", 0)),
            "thumbnail": s.get("thumbnails", {}).get("high", {}).get("url", ""),
        }
    except HttpError:
        return None


# ──────────────────────────────────────────────
# 댓글 + 대댓글 수집
# ──────────────────────────────────────────────
def get_comments_with_replies(youtube, video_id, max_comments=100, include_replies=False):
    comments = []
    next_page_token = None

    while len(comments) < max_comments:
        try:
            part_value = "snippet,replies" if include_replies else "snippet"
            resp = youtube.commentThreads().list(
                part=part_value,
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                pageToken=next_page_token,
                order="relevance",
                textFormat="plainText",
            ).execute()
        except HttpError as e:
            st.error(f"API 오류: {str(e)}")
            break

        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "유형": "댓글",
                "작성자": top.get("authorDisplayName", ""),
                "댓글": top.get("textDisplay", ""),
                "좋아요": top.get("likeCount", 0),
                "작성일": top.get("publishedAt", "")[:10],
            })

            if include_replies and "replies" in item:
                for reply in item["replies"]["comments"]:
                    r = reply["snippet"]
                    comments.append({
                        "유형": "↳ 답글",
                        "작성자": r.get("authorDisplayName", ""),
                        "댓글": r.get("textDisplay", ""),
                        "좋아요": r.get("likeCount", 0),
                        "작성일": r.get("publishedAt", "")[:10],
                    })

        next_page_token = resp.get("nextPageToken")
        if not next_page_token:
            break

    return comments


# ──────────────────────────────────────────────
# 감성 분석 (키워드 기반)
# ──────────────────────────────────────────────
POSITIVE_WORDS = [
    "좋아", "최고", "감사", "대박", "사랑", "행복", "굿", "멋지", "훌륭",
    "재밌", "재미", "웃기", "감동", "응원", "축하", "잘했", "잘한", "좋은",
    "완벽", "추천", "존경", "힐링", "편안", "기대", "설레", "짱",
    "awesome", "good", "great", "best", "love", "nice", "cool",
    "amazing", "wonderful", "beautiful", "fantastic", "excellent",
    "perfect", "wow", "thank",
]

NEGATIVE_WORDS = [
    "싫어", "최악", "별로", "짜증", "화나", "실망", "후회", "거짓", "나쁜",
    "못한", "쓰레기", "지루", "노잼", "그만", "비추", "혐오", "역겨",
    "답답", "한심", "어이없", "황당", "불쾌",
    "bad", "worst", "hate", "terrible", "awful", "boring", "ugly",
    "horrible", "disgusting", "disappointed", "annoying", "stupid",
]


def analyze_sentiment(text):
    text_lower = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    if pos > neg:
        return "긍정 😊"
    elif neg > pos:
        return "부정 😞"
    else:
        return "중립 😐"


# ──────────────────────────────────────────────
# 불용어
# ──────────────────────────────────────────────
STOPWORDS_KR = {
    "이", "그", "저", "것", "수", "등", "더", "좀", "를", "을",
    "에", "의", "가", "은", "는", "로", "으로", "와", "과", "도",
    "에서", "까지", "부터", "한", "하는", "된", "되는", "할", "하고",
    "있는", "없는", "해서", "하면", "이런", "저런", "그런", "합니다",
    "입니다", "습니다", "the", "a", "an", "is", "are", "was", "were",
    "be", "to", "of", "and", "in", "that", "it", "for", "on", "with",
    "as", "at", "by", "this", "from", "or", "not", "but", "if", "so",
    "what", "there", "my", "me", "you", "your", "they", "we", "he",
    "she", "do", "did", "have", "has", "just", "like", "get", "got",
    "can", "will", "one", "all", "would", "about", "up", "out", "how",
    "when", "which", "their", "been", "its",
}


# ──────────────────────────────────────────────
# 워드클라우드 생성 (폰트 경로 포함 - 핵심 수정)
# ──────────────────────────────────────────────
def generate_wordcloud(texts):
    combined = " ".join(texts)
    words = re.findall(r"[가-힣a-zA-Z]{2,}", combined)
    filtered = [w for w in words if w.lower() not in STOPWORDS_KR]
    if not filtered:
        return None
    word_freq = Counter(filtered)

    # 한글 폰트 경로 지정 (핵심!)
    font = FONT_PATH if os.path.exists(FONT_PATH) else None

    wc = WordCloud(
        font_path=font,
        width=800,
        height=400,
        background_color="white",
        max_words=100,
        colormap="Set2",
        prefer_horizontal=0.7,
    ).generate_from_frequencies(word_freq)
    return wc


# ──────────────────────────────────────────────
# Excel 내보내기
# ──────────────────────────────────────────────
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="댓글")
        ws = writer.sheets["댓글"]
        for col_cells in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 60)
    return output.getvalue()


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
api_key = get_api_key()

if not api_key:
    st.warning("⚠️ YouTube API 키가 설정되지 않았습니다.")
    st.info(
        "**설정 방법:**\n"
        "1. [Google Cloud Console](https://console.cloud.google.com/) 에서 프로젝트 생성\n"
        "2. YouTube Data API v3 활성화\n"
        "3. API 키 생성\n"
        "4. Streamlit Cloud → Settings → Secrets 에 아래 내용 추가:\n\n"
        '```\nYOUTUBE_API_KEY = "발급받은_API_키"\n```'
    )
    st.stop()

# ── 입력 영역 ──
st.markdown("---")
col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    url = st.text_input(
        "🔗 유튜브 영상 URL",
        placeholder="https://www.youtube.com/watch?v=...",
    )

with col2:
    max_comments = st.selectbox(
        "📝 최대 댓글 수",
        options=[50, 100, 200, 500, 1000],
        index=1,
    )

with col3:
    include_replies = st.checkbox("💬 대댓글 포함", value=False)

# ── 실행 ──
if st.button("🚀 댓글 수집 & 분석 시작", use_container_width=True, type="primary"):

    if not url.strip():
        st.warning("URL을 입력해주세요.")
        st.stop()

    video_id = extract_video_id(url.strip())
    if not video_id:
        st.error("올바른 유튜브 URL이 아닙니다.")
        st.stop()

    youtube = build("youtube", "v3", developerKey=api_key)

    with st.spinner("영상 정보를 불러오는 중..."):
        info = get_video_info(youtube, video_id)

    if info is None:
        st.error("영상 정보를 가져올 수 없습니다.")
        st.stop()

    with st.spinner(f"댓글을 수집하는 중... (최대 {max_comments}개)"):
        comments = get_comments_with_replies(youtube, video_id, max_comments, include_replies)

    if not comments:
        st.info("수집된 댓글이 없습니다.")
        st.stop()

    df = pd.DataFrame(comments)
    df["감성"] = df["댓글"].apply(analyze_sentiment)

    st.session_state["df"] = df
    st.session_state["video_id"] = video_id
    st.session_state["info"] = info


# ── 결과 표시 ──
if "df" in st.session_state:
    df = st.session_state["df"]
    video_id = st.session_state["video_id"]
    info = st.session_state["info"]

    # 영상 정보
    st.markdown("---")
    col_thumb, col_info = st.columns([1, 2])
    with col_thumb:
        if info["thumbnail"]:
            st.image(info["thumbnail"], use_container_width=True)
    with col_info:
        st.subheader(info["title"])
        st.markdown(f"**채널:** {info['channel']}　|　**게시일:** {info['published']}")
        m1, m2, m3 = st.columns(3)
        m1.metric("조회수", f"{info['views']:,}")
        m2.metric("좋아요", f"{info['likes']:,}")
        m3.metric("댓글 수", f"{info['comment_count']:,}")

    comment_count = len(df[df["유형"] == "댓글"])
    reply_count = len(df[df["유형"] != "댓글"])
    st.success(f"✅ 총 **{len(df)}개** 수집 완료! (댓글 {comment_count}개 + 답글 {reply_count}개)")

    # 폰트 상태 확인
    if not os.path.exists(FONT_PATH):
        st.warning(
            "⚠️ 한글 폰트 파일이 없습니다! 워드클라우드에서 한글이 깨질 수 있습니다.\n\n"
            "`fonts/NanumGothic.ttf` 파일을 프로젝트에 추가해주세요."
        )

    # 감성 색상맵
    color_map = {
        "긍정 😊": "#28a745",
        "부정 😞": "#dc3545",
        "중립 😐": "#6c757d",
    }

    # ════════════════════════════════════════════
    # 탭 구성
    # ════════════════════════════════════════════
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "💬 댓글 보기",
        "📊 감성 분석",
        "☁️ 워드클라우드",
        "📈 통계 차트",
        "👥 작성자 분석",
    ])

    # ──────────────────────────────────────
    # 탭 1: 댓글 보기
    # ──────────────────────────────────────
    with tab1:
        col_sort, col_search = st.columns([1, 2])
        with col_sort:
            sort_opt = st.radio("정렬", ["관련도순", "좋아요순", "최신순"], horizontal=True)
        with col_search:
            keyword = st.text_input("🔍 키워드 검색", "", key="kw1")

        df_view = df.copy()
        if sort_opt == "좋아요순":
            df_view = df_view.sort_values("좋아요", ascending=False)
        elif sort_opt == "최신순":
            df_view = df_view.sort_values("작성일", ascending=False)

        if keyword:
            df_view = df_view[df_view["댓글"].str.contains(keyword, case=False, na=False)]
            st.info(f"'{keyword}' 검색 결과: {len(df_view)}개")

        sentiment_filter = st.multiselect(
            "감성 필터",
            options=["긍정 😊", "부정 😞", "중립 😐"],
            default=["긍정 😊", "부정 😞", "중립 😐"],
        )
        df_view = df_view[df_view["감성"].isin(sentiment_filter)].reset_index(drop=True)

        page_size = 20
        total_pages = max(1, (len(df_view) - 1) // page_size + 1)
        page = st.number_input("페이지", min_value=1, max_value=total_pages, value=1, key="page1")
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        st.caption(
            f"총 {len(df_view)}개 중 {start_idx+1}~{min(end_idx, len(df_view))}번째 "
            f"(전체 {total_pages}페이지)"
        )

        for _, row in df_view.iloc[start_idx:end_idx].iterrows():
            box_class = "reply-box" if row["유형"] != "댓글" else "comment-box"
            if "긍정" in row["감성"]:
                s_class = "positive"
            elif "부정" in row["감성"]:
                s_class = "negative"
            else:
                s_class = "neutral"

            st.markdown(
                f'<div class="{box_class}">'
                f'<div class="comment-author">{row["유형"]} {row["작성자"]}'
                f'<span class="{s_class}" style="float:right;">{row["감성"]}</span></div>'
                f'<div class="comment-text">{row["댓글"]}</div>'
                f'<div class="comment-meta">👍 {row["좋아요"]}　|　{row["작성일"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with st.expander("📋 표 형태로 보기"):
            st.dataframe(df_view, use_container_width=True, height=400)

    # ──────────────────────────────────────
    # 탭 2: 감성 분석
    # ──────────────────────────────────────
    with tab2:
        st.subheader("📊 감성 분석 결과")

        sentiment_counts = df["감성"].value_counts()
        col_pie, col_bar = st.columns(2)

        with col_pie:
            fig_pie = px.pie(
                values=sentiment_counts.values,
                names=sentiment_counts.index,
                title="감성 비율",
                color=sentiment_counts.index,
                color_discrete_map=color_map,
            )
            fig_pie.update_traces(textinfo="percent+label")
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_bar:
            fig_bar = px.bar(
                x=sentiment_counts.index,
                y=sentiment_counts.values,
                title="감성별 댓글 수",
                labels={"x": "감성", "y": "댓글 수"},
                color=sentiment_counts.index,
                color_discrete_map=color_map,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("### 📌 감성별 좋아요 Top 3 댓글")
        for sentiment in ["긍정 😊", "부정 😞", "중립 😐"]:
            subset = df[df["감성"] == sentiment].sort_values("좋아요", ascending=False).head(3)
            if not subset.empty:
                st.markdown(f"**{sentiment}**")
                for _, row in subset.iterrows():
                    display_text = row["댓글"][:150]
                    st.markdown(f"> 👍 {row['좋아요']} | **{row['작성자']}**: {display_text}")

    # ──────────────────────────────────────
    # 탭 3: 워드클라우드
    # ──────────────────────────────────────
    with tab3:
        st.subheader("☁️ 워드클라우드")

        wc_option = st.radio(
            "대상 선택",
            ["전체 댓글", "긍정 댓글만", "부정 댓글만"],
            horizontal=True,
            key="wc_opt",
        )
        if wc_option == "긍정 댓글만":
            texts = df[df["감성"] == "긍정 😊"]["댓글"].tolist()
        elif wc_option == "부정 댓글만":
            texts = df[df["감성"] == "부정 😞"]["댓글"].tolist()
        else:
            texts = df["댓글"].tolist()

        wc = generate_wordcloud(texts)
        if wc:
            fig_wc, ax = plt.subplots(figsize=(14, 7))
            ax.imshow(wc, interpolation="bilinear")
            ax.axis("off")
            ax.set_title("댓글 워드클라우드", fontsize=16, pad=15)
            plt.tight_layout()
            st.pyplot(fig_wc)
            plt.close(fig_wc)
        else:
            st.info("워드클라우드를 생성할 단어가 부족합니다.")

        st.markdown("### 📋 자주 등장하는 단어 Top 20")
        combined = " ".join(texts)
        words = re.findall(r"[가-힣a-zA-Z]{2,}", combined)
        filtered = [w for w in words if w.lower() not in STOPWORDS_KR]
        word_freq = Counter(filtered).most_common(20)
        if word_freq:
            df_freq = pd.DataFrame(word_freq, columns=["단어", "빈도"])
            fig_freq = px.bar(
                df_freq, x="빈도", y="단어", orientation="h",
                title="단어 빈도 Top 20",
                color="빈도",
                color_continuous_scale="Reds",
            )
            fig_freq.update_layout(yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_freq, use_container_width=True)

    # ──────────────────────────────────────
    # 탭 4: 통계 차트
    # ──────────────────────────────────────
    with tab4:
        st.subheader("📈 댓글 통계")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 댓글 수", f"{len(df):,}")
        c2.metric("평균 좋아요", f"{df['좋아요'].mean():.1f}")
        c3.metric("최대 좋아요", f"{df['좋아요'].max():,}")
        avg_len = df["댓글"].str.len().mean()
        c4.metric("평균 글자 수", f"{avg_len:.0f}자")

        st.markdown("### 📅 날짜별 댓글 수 추이")
        df_date = df.groupby("작성일").size().reset_index(name="댓글수")
        df_date = df_date.sort_values("작성일")
        fig_timeline = px.line(
            df_date, x="작성일", y="댓글수",
            title="날짜별 댓글 수", markers=True,
        )
        fig_timeline.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_timeline, use_container_width=True)

        st.markdown("### 👍 좋아요 분포")
        fig_hist = px.histogram(
            df, x="좋아요", nbins=30,
            title="댓글 좋아요 분포",
            labels={"좋아요": "좋아요 수", "count": "댓글 수"},
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        st.markdown("### 📏 댓글 길이 분포")
        df_temp = df.copy()
        df_temp["글자수"] = df_temp["댓글"].str.len()
        fig_len = px.histogram(
            df_temp, x="글자수", nbins=30,
            title="댓글 길이 분포",
            labels={"글자수": "글자 수", "count": "댓글 수"},
            color_discrete_sequence=["#FF6B6B"],
        )
        st.plotly_chart(fig_len, use_container_width=True)

        st.markdown("### 📅 감성별 날짜 추이")
        df_sent_date = df.groupby(["작성일", "감성"]).size().reset_index(name="댓글수")
        fig_sent_time = px.line(
            df_sent_date, x="작성일", y="댓글수", color="감성",
            title="날짜별 감성 추이",
            color_discrete_map=color_map,
            markers=True,
        )
        st.plotly_chart(fig_sent_time, use_container_width=True)

    # ──────────────────────────────────────
    # 탭 5: 작성자 분석
    # ──────────────────────────────────────
    with tab5:
        st.subheader("👥 작성자별 분석")

        author_stats = df.groupby("작성자").agg(
            댓글수=("댓글", "count"),
            총좋아요=("좋아요", "sum"),
            평균좋아요=("좋아요", "mean"),
        ).sort_values("댓글수", ascending=False).reset_index()

        st.markdown("### 🏆 가장 많이 댓글을 단 사용자 Top 15")
        top_authors = author_stats.head(15)
        fig_author = px.bar(
            top_authors,
            x="댓글수",
            y="작성자",
            orientation="h",
            title="작성자별 댓글 수 Top 15",
            color="댓글수",
            color_continuous_scale="Blues",
        )
        fig_author.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_author, use_container_width=True)

        st.markdown("### 💖 좋아요를 가장 많이 받은 사용자 Top 15")
        top_liked = author_stats.sort_values("총좋아요", ascending=False).head(15)
        fig_liked = px.bar(
            top_liked,
            x="총좋아요",
            y="작성자",
            orientation="h",
            title="작성자별 총 좋아요 Top 15",
            color="총좋아요",
            color_continuous_scale="Oranges",
        )
        fig_liked.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_liked, use_container_width=True)

        st.markdown("### 📋 작성자 전체 통계표")
        author_stats["평균좋아요"] = author_stats["평균좋아요"].round(1)
        st.dataframe(author_stats, use_container_width=True, height=400)

    # ════════════════════════════════════════════
    # 다운로드 영역
    # ════════════════════════════════════════════
    st.markdown("---")
    st.subheader("📥 데이터 다운로드")

    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        csv_data = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📄 CSV 다운로드",
            data=csv_data,
            file_name=f"youtube_comments_{video_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with dl_col2:
        excel_data = to_excel(df)
        st.download_button(
            label="📊 Excel 다운로드",
            data=excel_data,
            file_name=f"youtube_comments_{video_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
