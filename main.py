import streamlit as st
import pandas as pd
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="유튜브 댓글 수집기",
    page_icon="📺",
    layout="wide",
)

# ──────────────────────────────────────────────
# CSS 스타일
# ──────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #FF0000;
        text-align: center;
        margin-bottom: 0.5rem;
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
    .comment-author {
        font-weight: 700;
        color: #333;
        margin-bottom: 4px;
    }
    .comment-text {
        color: #555;
        line-height: 1.6;
    }
    .comment-meta {
        color: #999;
        font-size: 0.85rem;
        margin-top: 4px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">📺 유튜브 댓글 수집기</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">유튜브 영상 링크를 입력하면 댓글을 불러옵니다</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# API 키 불러오기
# ──────────────────────────────────────────────
def get_api_key():
    """Streamlit secrets 에서 API 키를 가져온다."""
    try:
        return st.secrets["YOUTUBE_API_KEY"]
    except Exception:
        return None


# ──────────────────────────────────────────────
# 영상 ID 추출
# ──────────────────────────────────────────────
def extract_video_id(url: str) -> str | None:
    """다양한 유튜브 URL 형식에서 video_id를 추출한다."""
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",           # 일반 링크
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",    # 단축 링크
        r"(?:embed/)([a-zA-Z0-9_-]{11})",         # 임베드 링크
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",        # 쇼츠 링크
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ──────────────────────────────────────────────
# 영상 정보 가져오기
# ──────────────────────────────────────────────
def get_video_info(youtube, video_id: str) -> dict | None:
    """영상 제목, 채널명, 조회수 등 기본 정보를 가져온다."""
    try:
        response = youtube.videos().list(
            part="snippet,statistics",
            id=video_id
        ).execute()

        if not response["items"]:
            return None

        item = response["items"][0]
        snippet = item["snippet"]
        stats = item["statistics"]

        return {
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published": snippet.get("publishedAt", "")[:10],
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
        }
    except HttpError:
        return None


# ──────────────────────────────────────────────
# 댓글 수집
# ──────────────────────────────────────────────
def get_comments(youtube, video_id: str, max_comments: int = 100) -> list[dict]:
    """
    최상위 댓글을 최대 max_comments 개까지 수집한다.
    YouTube Data API 의 commentThreads 엔드포인트를 사용한다.
    """
    comments = []
    next_page_token = None

    while len(comments) < max_comments:
        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_comments - len(comments)),
                pageToken=next_page_token,
                order="relevance",
                textFormat="plainText",
            ).execute()
        except HttpError as e:
            error_reason = e.error_details[0]["reason"] if e.error_details else str(e)
            st.error(f"API 오류: {error_reason}")
            break

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "작성자": snippet.get("authorDisplayName", ""),
                "댓글": snippet.get("textDisplay", ""),
                "좋아요": snippet.get("likeCount", 0),
                "작성일": snippet.get("publishedAt", "")[:10],
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return comments


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
api_key = get_api_key()

if not api_key:
    st.warning("⚠️ YouTube API 키가 설정되지 않았습니다.")
    st.info(
        "**설정 방법:**\n"
        "1. [Google Cloud Console](https://console.cloud.google.com/) 에서 프로젝트를 만드세요.\n"
        "2. YouTube Data API v3 를 활성화하세요.\n"
        "3. API 키를 생성하세요.\n"
        "4. Streamlit Cloud → 앱 Settings → Secrets 에 아래 내용을 추가하세요:\n"
        "```\n"
        'YOUTUBE_API_KEY = "발급받은_API_키"\n'
        "```"
    )
    st.stop()

# 입력 영역
st.markdown("---")
col_input, col_option = st.columns([3, 1])

with col_input:
    url = st.text_input(
        "🔗 유튜브 영상 URL을 입력하세요",
        placeholder="https://www.youtube.com/watch?v=...",
    )

with col_option:
    max_comments = st.selectbox(
        "📝 최대 댓글 수",
        options=[50, 100, 200, 500, 1000],
        index=1,
    )

# 실행 버튼
if st.button("🚀 댓글 불러오기", use_container_width=True, type="primary"):

    if not url.strip():
        st.warning("URL을 입력해주세요.")
        st.stop()

    video_id = extract_video_id(url.strip())

    if not video_id:
        st.error("올바른 유튜브 URL이 아닙니다. 다시 확인해주세요.")
        st.stop()

    # YouTube API 클라이언트 생성
    youtube = build("youtube", "v3", developerKey=api_key)

    # ── 영상 정보 표시 ──
    with st.spinner("영상 정보를 불러오는 중..."):
        info = get_video_info(youtube, video_id)

    if info is None:
        st.error("영상 정보를 가져올 수 없습니다. URL을 확인해주세요.")
        st.stop()

    st.markdown("---")
    col_thumb, col_info = st.columns([1, 2])

    with col_thumb:
        if info["thumbnail"]:
            st.image(info["thumbnail"], use_container_width=True)

    with col_info:
        st.subheader(info["title"])
        st.markdown(f"**채널:** {info['channel']}")
        st.markdown(f"**게시일:** {info['published']}")
        st.markdown(
            f"**조회수:** {info['views']:,}　|　"
            f"**좋아요:** {info['likes']:,}　|　"
            f"**댓글 수:** {info['comment_count']:,}"
        )

    # ── 댓글 수집 ──
    st.markdown("---")
    with st.spinner(f"댓글을 수집하는 중... (최대 {max_comments}개)"):
        comments = get_comments(youtube, video_id, max_comments)

    if not comments:
        st.info("수집된 댓글이 없습니다. 댓글이 비활성화된 영상일 수 있습니다.")
        st.stop()

    st.success(f"✅ 총 **{len(comments)}개** 의 댓글을 수집했습니다!")

    # ── 탭: 카드 보기 / 표 보기 ──
    tab_card, tab_table = st.tabs(["💬 카드 보기", "📊 표 보기"])

    df = pd.DataFrame(comments)

    with tab_card:
        # 정렬 옵션
        sort_option = st.radio(
            "정렬 기준",
            ["관련도순 (기본)", "좋아요 많은 순", "최신순"],
            horizontal=True,
        )
        if sort_option == "좋아요 많은 순":
            df_sorted = df.sort_values("좋아요", ascending=False).reset_index(drop=True)
        elif sort_option == "최신순":
            df_sorted = df.sort_values("작성일", ascending=False).reset_index(drop=True)
        else:
            df_sorted = df.copy()

        # 검색 필터
        search_keyword = st.text_input("🔍 댓글 내 키워드 검색", "")
        if search_keyword:
            mask = df_sorted["댓글"].str.contains(search_keyword, case=False, na=False)
            df_sorted = df_sorted[mask].reset_index(drop=True)
            st.info(f"'{search_keyword}' 포함 댓글: {len(df_sorted)}개")

        # 카드 출력
        for _, row in df_sorted.iterrows():
            st.markdown(
                f"""
                <div class="comment-box">
                    <div class="comment-author">{row['작성자']}</div>
                    <div class="comment-text">{row['댓글']}</div>
                    <div class="comment-meta">👍 {row['좋아요']}　|　{row['작성일']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with tab_table:
        st.dataframe(df, use_container_width=True, height=500)

    # ── CSV 다운로드 ──
    st.markdown("---")
    csv_data = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 댓글 CSV 다운로드",
        data=csv_data,
        file_name=f"youtube_comments_{video_id}.csv",
        mime="text/csv",
        use_container_width=True,
    )
