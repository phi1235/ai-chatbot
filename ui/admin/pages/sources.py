from __future__ import annotations

import streamlit as st

from ui.admin.api_client import add_url, delete_url, get_sources, trigger_ingest
from ui.admin.page_shell import render_page_header


def parse_url_lines(text: str) -> list[tuple[str, str]]:
    """Parse textarea: mỗi dòng 1 URL."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            url, title = (s.strip() for s in line.split("|", 1))
        else:
            url, title = line, ""
        if url:
            out.append((url, title))
    return out


def bulk_add_urls(topic: str, url_lines: list[tuple[str, str]], crawl_after: bool) -> tuple[int, int, list[str]]:
    added = 0
    skipped = 0
    errors: list[str] = []
    for url, title in url_lines:
        ok, msg = add_url(topic, url, title)
        if ok:
            added += 1
        elif "đã tồn tại" in msg.lower() or "already" in msg.lower():
            skipped += 1
        else:
            errors.append(f"{url}: {msg}")

    if crawl_after and added > 0:
        with st.spinner(f"Đang crawl + index {topic}..."):
            res = trigger_ingest(topic=topic)
        if res:
            st.info(
                f"Đã crawl: {res['documents_crawled']} docs, "
                f"{res['chunks_indexed']} chunks"
            )
    return added, skipped, errors


def page_sources():
    render_page_header(
        "Sources",
        "Quản lý nguồn dữ liệu được crawl vào knowledge base",
    )

    st.markdown('<div class="card-title">Thêm topic mới (hoặc thêm vào topic có sẵn)</div>', unsafe_allow_html=True)
    with st.form("add_topic_form", clear_on_submit=True):
        new_topic = st.text_input("Tên topic", placeholder="vd: kubernetes, react, fastapi")
        url_block = st.text_area(
            "Danh sách URL (mỗi dòng 1 URL)",
            placeholder=(
                "https://docs.example.com/page-1\n"
                "https://docs.example.com/page-2 | Tiêu đề tuỳ chỉnh\n"
                "# Dòng bắt đầu '#' sẽ bị bỏ qua\n"
                "https://docs.example.com/page-3"
            ),
            height=150,
            help='Format: "URL" hoặc "URL | Title". Comment bằng "#".',
        )
        bcols = st.columns([2, 1])
        with bcols[0]:
            crawl_after_add = st.checkbox(
                "Crawl + index ngay sau khi thêm",
                value=True,
                help="Tự động re-crawl toàn bộ topic ngay sau khi thêm xong.",
            )
        with bcols[1]:
            submit = st.form_submit_button("Thêm vào sources", type="primary", use_container_width=True)
        if submit:
            topic_clean = (new_topic or "").strip()
            url_lines = parse_url_lines(url_block or "")
            if not topic_clean:
                st.error("Cần nhập tên topic.")
            elif not url_lines:
                st.error("Cần ít nhất 1 URL.")
            else:
                added, skipped, errors = bulk_add_urls(topic_clean, url_lines, crawl_after_add)
                msg_parts = []
                if added:
                    msg_parts.append(f"thêm {added}")
                if skipped:
                    msg_parts.append(f"đã có {skipped}")
                if errors:
                    msg_parts.append(f"lỗi {len(errors)}")
                summary = " · ".join(msg_parts) or "không có thay đổi"
                if errors:
                    st.warning(summary)
                    with st.expander("Chi tiết lỗi"):
                        for err in errors:
                            st.text(f"- {err}")
                else:
                    st.success(summary)

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Crawl ad-hoc (không lưu vào sources file)</div>', unsafe_allow_html=True)
    with st.form("adhoc_crawl"):
        c = st.columns([1, 3, 1])
        with c[0]:
            adhoc_topic = st.text_input(
                "Topic",
                value="general",
                key="adhoc_topic",
                label_visibility="collapsed",
                placeholder="topic",
            )
        with c[1]:
            adhoc_url = st.text_input(
                "URL",
                placeholder="https://...",
                key="adhoc_url",
                label_visibility="collapsed",
            )
        with c[2]:
            adhoc_submit = st.form_submit_button("Crawl ngay", use_container_width=True)
        if adhoc_submit and adhoc_url:
            with st.spinner("Đang crawl + index..."):
                res = trigger_ingest(
                    urls=[
                        {
                            "location": adhoc_url.strip(),
                            "topic": adhoc_topic.strip() or "general",
                            "title": adhoc_url.strip(),
                            "source": "website",
                        }
                    ]
                )
            if res:
                st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")

    st.markdown("&nbsp;")
    st.markdown('<div class="card-title">Topics hiện có</div>', unsafe_allow_html=True)

    topics_all = get_sources()
    if not topics_all:
        st.info("Chưa có topic nào. Thêm URL ở form trên để tạo topic mới.")
        return

    fcols = st.columns([3, 1, 1])
    with fcols[0]:
        search_q = st.text_input(
            "Tìm topic",
            placeholder="Nhập tên topic hoặc URL để lọc...",
            key="topic_search",
            label_visibility="collapsed",
        )
    with fcols[1]:
        sort_by = st.selectbox(
            "Sắp xếp",
            options=["Tên (A→Z)", "Tên (Z→A)", "URLs nhiều nhất", "URLs ít nhất"],
            label_visibility="collapsed",
            key="topic_sort",
        )
    with fcols[2]:
        page_size = st.selectbox(
            "Mỗi trang",
            options=[5, 10, 20, 50],
            index=1,
            label_visibility="collapsed",
            key="topic_page_size",
        )

    q = (search_q or "").strip().lower()
    if q:
        def match(topic_item: dict) -> bool:
            if q in topic_item["topic"].lower():
                return True
            return any(
                q in (it.get("location") or "").lower() or q in (it.get("title") or "").lower()
                for it in topic_item.get("items", [])
            )

        topics = [topic_item for topic_item in topics_all if match(topic_item)]
    else:
        topics = list(topics_all)

    if sort_by == "Tên (A→Z)":
        topics.sort(key=lambda topic_item: topic_item["topic"].lower())
    elif sort_by == "Tên (Z→A)":
        topics.sort(key=lambda topic_item: topic_item["topic"].lower(), reverse=True)
    elif sort_by == "URLs nhiều nhất":
        topics.sort(key=lambda topic_item: topic_item["count"], reverse=True)
    else:
        topics.sort(key=lambda topic_item: topic_item["count"])

    total = len(topics)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page_key = "topic_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1

    state_sig = f"{q}|{sort_by}|{page_size}|{len(topics_all)}"
    if st.session_state.get("topic_state_sig") != state_sig:
        st.session_state["topic_state_sig"] = state_sig
        st.session_state[page_key] = 1
    current_page = min(st.session_state[page_key], total_pages)

    start = (current_page - 1) * page_size
    end = start + page_size
    visible = topics[start:end]

    filter_info = f"{total} / {len(topics_all)} topic" if q else f"{total} topic"
    st.caption(f"{filter_info} · Trang {current_page}/{total_pages}")

    if not visible:
        st.info("Không có topic nào khớp filter.")
        return

    for topic_item in visible:
        with st.expander(f"**{topic_item['topic']}** · {topic_item['count']} URLs", expanded=False):
            cols = st.columns([3, 1])
            with cols[0]:
                st.caption(f"File: `{topic_item['file']}`")
            with cols[1]:
                if st.button(
                    "Re-crawl topic",
                    key=f"recrawl-{topic_item['topic']}",
                    use_container_width=True,
                ):
                    with st.spinner(f"Đang re-crawl {topic_item['topic']}..."):
                        res = trigger_ingest(topic=topic_item["topic"])
                    if res:
                        st.success(f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks")

            with st.form(f"add_to_{topic_item['topic']}", clear_on_submit=True):
                st.caption(f"Thêm URL vào topic `{topic_item['topic']}` (mỗi dòng 1 URL):")
                more_urls = st.text_area(
                    "URLs",
                    placeholder="https://...\nhttps://... | Title",
                    height=100,
                    key=f"more-{topic_item['topic']}",
                    label_visibility="collapsed",
                )
                ac = st.columns([2, 1])
                with ac[0]:
                    crawl_now = st.checkbox(
                        "Crawl ngay sau khi thêm",
                        value=True,
                        key=f"crawl-now-{topic_item['topic']}",
                    )
                with ac[1]:
                    if st.form_submit_button("Thêm", use_container_width=True):
                        url_lines = parse_url_lines(more_urls or "")
                        if not url_lines:
                            st.error("Chưa nhập URL nào.")
                        else:
                            added, skipped, errors = bulk_add_urls(topic_item["topic"], url_lines, crawl_now)
                            if added:
                                st.success(f"Thêm {added} URLs vào {topic_item['topic']}")
                            if skipped:
                                st.info(f"{skipped} URLs đã có sẵn (bỏ qua)")
                            if errors:
                                st.warning(f"{len(errors)} URLs lỗi")
                                with st.expander("Chi tiết"):
                                    for err in errors:
                                        st.text(f"- {err}")
                            if added or errors:
                                st.rerun()

            if not topic_item["items"]:
                st.caption("(rỗng)")
            else:
                topic = topic_item["topic"]
                sel_state_key = f"sel_urls_{topic}"
                if sel_state_key not in st.session_state:
                    st.session_state[sel_state_key] = set()
                selected = st.session_state[sel_state_key]

                tcols = st.columns([2, 2, 2, 1])
                with tcols[0]:
                    if st.button(
                        "Chọn tất cả",
                        key=f"selall-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == len(topic_item["items"]),
                    ):
                        st.session_state[sel_state_key] = {it["location"] for it in topic_item["items"]}
                        st.rerun()
                with tcols[1]:
                    if st.button(
                        "Bỏ chọn",
                        key=f"selnone-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == 0,
                    ):
                        st.session_state[sel_state_key] = set()
                        st.rerun()
                with tcols[2]:
                    if st.button(
                        f"Re-crawl đã chọn ({len(selected)})",
                        key=f"recrawl-sel-{topic}",
                        use_container_width=True,
                        disabled=len(selected) == 0,
                        type="primary",
                    ):
                        urls_to_crawl = [
                            {
                                "location": it["location"],
                                "topic": topic,
                                "title": it.get("title", it["location"]),
                                "source": it.get("source", "website"),
                            }
                            for it in topic_item["items"]
                            if it["location"] in selected
                        ]
                        with st.spinner(f"Re-crawl {len(urls_to_crawl)} URLs..."):
                            res = trigger_ingest(urls=urls_to_crawl)
                        if res:
                            st.success(
                                f"{res['documents_crawled']} docs, {res['chunks_indexed']} chunks"
                            )
                            st.session_state[sel_state_key] = set()

                for item in topic_item["items"]:
                    loc = item["location"]
                    row = st.columns([0.5, 4.5, 1])
                    with row[0]:
                        checked = st.checkbox(
                            "Sel",
                            value=loc in selected,
                            key=f"chk-{topic}-{loc}",
                            label_visibility="collapsed",
                        )
                        if checked and loc not in selected:
                            selected.add(loc)
                        elif not checked and loc in selected:
                            selected.discard(loc)
                    with row[1]:
                        st.markdown(
                            f'<div class="url-item">'
                            f'<div class="url-title">{item.get("title", loc)}</div>'
                            f'<div class="url-link">{loc}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with row[2]:
                        rcols = st.columns(2, gap="small")
                        with rcols[0]:
                            if st.button(
                                "↻",
                                key=f"recrawl-one-{topic}-{loc}",
                                help="Re-crawl URL này",
                                use_container_width=True,
                            ):
                                with st.spinner(f"Re-crawl {loc[:50]}..."):
                                    res = trigger_ingest(
                                        urls=[
                                            {
                                                "location": loc,
                                                "topic": topic,
                                                "title": item.get("title", loc),
                                                "source": item.get("source", "website"),
                                            }
                                        ]
                                    )
                                if res:
                                    st.success(f"{res['chunks_indexed']} chunks")
                        with rcols[1]:
                            if st.button(
                                "✕",
                                key=f"del-{topic}-{loc}",
                                help="Xoá URL khỏi sources",
                                use_container_width=True,
                            ):
                                if delete_url(topic, loc):
                                    selected.discard(loc)
                                    st.rerun()

    if total_pages > 1:
        st.markdown("&nbsp;")
        pcols = st.columns([1, 1, 3, 1, 1])
        with pcols[0]:
            if st.button("« Đầu", disabled=current_page == 1, use_container_width=True, key="pg_first"):
                st.session_state[page_key] = 1
                st.rerun()
        with pcols[1]:
            if st.button("‹ Trước", disabled=current_page == 1, use_container_width=True, key="pg_prev"):
                st.session_state[page_key] = current_page - 1
                st.rerun()
        with pcols[2]:
            jump = st.number_input(
                "Trang",
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                label_visibility="collapsed",
                key="pg_jump",
            )
            if jump != current_page:
                st.session_state[page_key] = int(jump)
                st.rerun()
        with pcols[3]:
            if st.button(
                "Sau ›",
                disabled=current_page >= total_pages,
                use_container_width=True,
                key="pg_next",
            ):
                st.session_state[page_key] = current_page + 1
                st.rerun()
        with pcols[4]:
            if st.button(
                "Cuối »",
                disabled=current_page >= total_pages,
                use_container_width=True,
                key="pg_last",
            ):
                st.session_state[page_key] = total_pages
                st.rerun()
