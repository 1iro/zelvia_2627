#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FC町田ゼルビア 試合日程・結果 自動更新スクリプト
================================================
公式サイト（zelvia.co.jp）の「試合日程・結果」ページを取得し、
J1リーグ / ルヴァンカップ / 天皇杯 の日程を schedule.json に反映する。

さらに、Jリーグ公式サイト（jleague.jp）のクラブページにある「戦績」表から
消化済み試合のスコアを取得し、日付が一致する試合（J1に限らず、天皇杯・
ルヴァンカップ・ACL2など schedule.json に載っている大会すべて）に
played / scoreZelvia / scoreOpp を書き込む。

- ACL2（AFCチャンピオンズリーグ2）の個別マッチデー日程は、公式ページの
  「試合日程一覧」にはまだ載らないことが多いため、このスクリプトでは
  既存の schedule.json 内の ACL2 エントリーをそのまま保持する（上書きしない）。
  AFC/クラブから正式な日程が出たら、schedule.json を手動で編集するか、
  このスクリプトに ACL2 用パーサーを追加してください。

- 日程パースは、生HTMLのタグ構造（改行の位置など）にできるだけ依存しないよう、
  「節・日付」「チーム画像(alt/src)」「スタジアム名/HOME・AWAY」の3つを別々に
  正規表現で抽出し、出現順にzipして組み立てる方式にしている。
  3つの抽出件数が一致しない場合はその大会のパースを諦める（安全側に倒す）。

- サイト構造が変わるとパースに失敗することがある。日程パースが失敗した場合は
  既存の schedule.json を壊さないよう、変更を書き込まずに終了する
  （GitHub Actions 側は差分が無ければ何もコミットしない）。
  スコア取得の失敗は致命的ではないため、失敗しても日程データだけは更新する。

使い方:
    python3 scripts/update_schedule.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.request import Request, urlopen

SCHEDULE_URL = "https://www.zelvia.co.jp/match/game/series/2026-27/"
RESULTS_URL = "https://www.jleague.jp/club/machida/"
LOGO_BASE = "https://www.zelvia.co.jp/wp-content/themes/zelvia/assets/img/team_logo/"
ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_JSON = ROOT / "schedule.json"

# 全角数字/全角記号を半角に正規化するためのヘルパ
def z2h(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def fetch_html(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    with urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


# 曜日文字 -> (sort用の分類, 表示ラベル)
DOW_CLASS = {
    "月": "wk", "火": "wk", "水": "wk", "木": "wk", "金": "wk",
    "土": "sat", "日": "sun",
}

MONTH_TO_SEASON_YEAR = {
    # 2026/27シーズン: 8月開幕、翌年6月終了という想定でシーズンをまたぐ年を判定
    8: 2026, 9: 2026, 10: 2026, 11: 2026, 12: 2026,
    1: 2027, 2: 2027, 3: 2027, 4: 2027, 5: 2027, 6: 2027, 7: 2027,
}

# 公式サイト側の表記ゆれ（略称・誤記）を正式名称に統一するための対応表。
# 例: 「Gスタ」は本来「町田GIONスタジアム」の略だが、公式サイト側で
#     まれに略称のまま掲載されてしまうことがあるため、ここで正規化する。
STADIUM_NORMALIZE = {
    "Gスタ": "町田GIONスタジアム",
    "町田GIONスタジアム": "町田GIONスタジアム",
    "町田ＧＩＯＮスタジアム": "町田GIONスタジアム",
}


def find_sections_raw(html: str):
    """
    生HTMLの中から、大会ごとの見出し（例:「2026/27明治安田J1リーグ」）を
    直接テキスト検索し、その見出しから次の見出しまでの生HTMLをスライスして返す。
    「### 」への変換（Markdown化）に依存しないので、見出しタグの実際の形が
    <h3> だろうと <div class="heading"> だろうと影響を受けない。
    """
    # 「試合日程一覧」以降だけを対象にする（直近の試合情報セクションとの重複を避ける）
    idx = html.find("試合日程一覧")
    search_area = html[idx:] if idx != -1 else html

    headings = [
        ("J1", ["明治安田J1リーグ", "明治安田Ｊ１リーグ"]),
        ("YBC", ["ヤマザキビスケットルヴァンカップ", "ルヴァンカップ"]),
        ("EMP", ["天皇杯"]),
        # ACL2自体は自動パース対象外だが、YBCセクションの終端を正しく区切るために見出しだけ認識する
        ("ACL2", ["AFCチャンピオンズリーグ", "ACL Two", "ACL2"]),
    ]

    # 各大会の見出しがテキスト中に最初に現れる位置を探す
    positions = []  # (start_index, comp_key)
    for comp_key, needles in headings:
        for needle in needles:
            pos = search_area.find(needle)
            if pos != -1:
                positions.append((pos, comp_key))
                break

    positions.sort(key=lambda x: x[0])

    sections = {}
    for i, (pos, comp_key) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(search_area)
        sections[comp_key] = search_area[pos:end]
    return sections


def strip_tags(html_fragment: str) -> str:
    """HTMLタグをすべて除去してプレーンテキストにする（改行の有無には依存しない設計にする）。"""
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t\r\n]+", " ", text)
    return text


def extract_round_date_blocks(plain_text: str):
    """
    「【第9節】10月10日（土）or 10月11日（日）未定〜」のような
    「節・日付・時刻」のブロックを、出現順にすべて抽出する。
    タグを含まない自己完結した文字列なので、tag stripping後のテキストに対して
    そのまま安定して使える。
    """
    pattern = re.compile(
        r"【(?P<round>[^】]+)】\s*"
        r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})日（(?P<dow1>[月火水木金土日])）"
        r"(?:or\s*(?P<m2>\d{1,2})月(?P<d2>\d{1,2})日（(?P<dow2>[月火水木金土日])）)?"
        r"\s*(?P<time>未定|\d{1,2}:\d{2})[〜~]"
    )
    return list(pattern.finditer(plain_text))


def extract_team_logo_images(html_fragment: str):
    """
    <img ... alt="チーム名" ... src="...team_logo/xxx.png" ...> のパターンを、
    alt/src の順序に関わらず出現順にすべて抽出する。
    src に "team_logo" を含むものだけを対象にし、パートナー企業ロゴ等の
    無関係な画像を自動的に除外する。
    """
    pattern = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
    results = []
    for m in pattern.finditer(html_fragment):
        tag = m.group(0)
        if "team_logo" not in tag and "/wp-content/uploads/" not in tag:
            continue
        alt_m = re.search(r'alt="([^"]*)"', tag)
        src_m = re.search(r'src="([^"]+)"', tag)
        if not src_m:
            continue
        alt = z2h(alt_m.group(1)).strip() if alt_m else ""
        src = src_m.group(1)
        results.append({"alt": alt, "src": src, "pos": m.start()})
    return results


def extract_stadium_ha_blocks(plain_text: str):
    """
    「スタジアム名/HOME」「スタジアム名/AWAY」のパターンを出現順にすべて抽出する。
    スタジアム名に "/" は含まれない前提（今のところ実データで例外なし）。
    """
    pattern = re.compile(r"([^\s/][^/]{0,58}?)\s*/\s*(HOME|AWAY)")
    return list(pattern.finditer(plain_text))


def parse_section(comp_key, section_html):
    """
    1つの大会セクションの生HTML（またはそれに準ずる断片）から、
    「節・日付」「チーム画像（alt=対戦相手名, src=ロゴURL）」「スタジアム/HOME|AWAY」を
    それぞれ独立に抽出し、出現順にzipして1試合ずつのエントリーに組み立てる。

    改行やタグの入れ子構造に依存しないため、サイトのマークアップが多少変わっても
    崩れにくい。スタジアム名は「各試合のチーム画像タグの位置」を基準に検索範囲を
    1試合分だけに絞り込むことで、見出しや前の試合のテキストを巻き込まないようにしている。
    3つのリストの件数が一致しない場合は、その大会のパースを諦めて空リストを返す
    （呼び出し側で件数チェックにより安全側に倒れる）。
    """
    plain = strip_tags(section_html)
    round_blocks = extract_round_date_blocks(plain)
    img_blocks = extract_team_logo_images(section_html)

    n = len(round_blocks)
    if n == 0 or len(img_blocks) < n:
        return []

    entries = []
    for i in range(n):
        d = round_blocks[i].groupdict()
        img = img_blocks[i]

        # このimgタグから次のimgタグ（無ければセクション末尾）までを、
        # この1試合だけの「持ち場」として切り出す
        window_start = img["pos"]
        window_end = img_blocks[i + 1]["pos"] if i + 1 < len(img_blocks) else len(section_html)
        window_html = section_html[window_start:window_end]
        window_plain = strip_tags(window_html)

        stadium_matches = list(extract_stadium_ha_blocks(window_plain))
        if not stadium_matches:
            continue
        stadium_m = stadium_matches[0]

        month1, day1 = int(d["m1"]), int(d["d1"])
        year1 = MONTH_TO_SEASON_YEAR.get(month1, 2026)
        sort_date = f"{year1:04d}-{month1:02d}-{day1:02d}"

        if d["m2"]:
            date_disp = f"{month1:02d}.{day1:02d} or {int(d['m2']):02d}.{int(d['d2']):02d}"
            day_label = f"{d['dow1']}/{d['dow2']}"
        else:
            date_disp = f"{month1:02d}.{day1:02d}"
            day_label = d["dow1"]

        day_class = DOW_CLASS.get(d["dow1"], "wk")
        time_disp = d["time"]

        opp_name = z2h(img["alt"]).strip()
        opp_name = re.split(r"\s*[○◯●△]\s*\d", opp_name)[0].strip()
        logo_file = img["src"].rsplit("/", 1)[-1]

        stadium_raw = z2h(stadium_m.group(1)).strip()
        # 先頭に紛れ込む「対戦相手名（＋スコア）」を取り除く
        if stadium_raw.startswith(opp_name):
            stadium_raw = stadium_raw[len(opp_name):].strip()
        stadium_raw = re.sub(r"^[○◯●△]\s*\d+\s*-\s*\d+\s*", "", stadium_raw).strip()
        stadium = STADIUM_NORMALIZE.get(stadium_raw, stadium_raw) or "未定"
        ha = stadium_m.group(2)

        round_raw = z2h(d["round"])
        round_num_match = re.match(r"第(\d+)節", round_raw)
        round_val = int(round_num_match.group(1)) if round_num_match else round_raw

        entries.append({
            "comp": comp_key,
            "round": round_val,
            "home": True if ha == "HOME" else False,
            "sort": sort_date,
            "date": date_disp,
            "day": day_class,
            "dayLabel": day_label,
            "time": time_disp,
            "opp": opp_name,
            "logo": logo_file,
            "stadium": stadium,
        })
    return entries



def extract_table_rows(html: str, near_heading: str):
    """
    指定した見出し文字列（例:「戦績」）の後に最初に現れる <table> を探し、
    行ごとにセルのテキストのリストとして返す。
    """
    idx = html.find(near_heading)
    if idx == -1:
        return []
    table_start = html.find("<table", idx)
    if table_start == -1:
        return []
    table_end = html.find("</table>", table_start)
    if table_end == -1:
        return []
    table_html = html[table_start:table_end]

    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
        clean_cells = []
        for c in cells:
            c = re.sub(r"<[^>]+>", "", c)
            c = z2h(c).strip()
            clean_cells.append(c)
        if clean_cells:
            rows.append(clean_cells)
    return rows


def parse_results(html: str):
    """
    jleague.jp クラブページの「戦績」表から、消化済み試合のスコアを抽出する。
    戻り値: [{"sort": "YYYY-MM-DD", "scoreZelvia": int, "scoreOpp": int}, ...]

    表の想定フォーマット（見出し行を含む）:
      年月日 | KO時刻 | 対戦相手 | 会場 | スコア | 大会 | ...
      26/8/23 | 19:36 | 浦和 | MUFG国立 | 勝 3-1 | 明治安田Ｊ１ | ...

    スコア欄は常に「町田自身の得点-相手の得点」の順で書かれているため、
    home/away を問わずそのまま scoreZelvia / scoreOpp として使える。
    """
    rows = extract_table_rows(html, "戦績")
    results = []
    date_re = re.compile(r"^(\d{2})/(\d{1,2})/(\d{1,2})$")
    score_re = re.compile(r"(\d+)\s*-\s*(\d+)")

    for row in rows:
        if not row or not date_re.match(row[0]):
            continue  # 見出し行や不正な行はスキップ
        yy, mm, dd = date_re.match(row[0]).groups()
        year = 2000 + int(yy)
        sort_date = f"{year:04d}-{int(mm):02d}-{int(dd):02d}"

        score_cell = next((c for c in row if score_re.search(c)), None)
        if not score_cell:
            continue
        m = score_re.search(score_cell)
        results.append({
            "sort": sort_date,
            "scoreZelvia": int(m.group(1)),
            "scoreOpp": int(m.group(2)),
        })
    return results


def main():
    try:
        raw_html = fetch_html(SCHEDULE_URL)
    except Exception as e:
        print(f"[ERROR] ページ取得に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    # --- 診断ログ: 取得できたHTMLの基本情報 ---
    print(f"[DEBUG] 取得したHTMLの長さ: {len(raw_html)} 文字", file=sys.stderr)
    for needle in ["試合日程一覧", "明治安田J1リーグ", "明治安田Ｊ１リーグ",
                   "ルヴァンカップ", "天皇杯", "team_logo", "<img"]:
        print(f"[DEBUG] '{needle}' を含むか: {needle in raw_html}", file=sys.stderr)

    sections = find_sections_raw(raw_html)
    print(f"[DEBUG] 見つかったセクション: {list(sections.keys())}", file=sys.stderr)
    for k, v in sections.items():
        print(f"[DEBUG]   {k} セクションの長さ: {len(v)} 文字", file=sys.stderr)

    new_entries = []
    if "J1" in sections:
        j1_entries = parse_section("J1", sections["J1"])
        print(f"[DEBUG] J1 パース結果: {len(j1_entries)} 件", file=sys.stderr)
        new_entries += j1_entries
    else:
        print("[DEBUG] J1 セクションが見つかりませんでした", file=sys.stderr)

    if "YBC" in sections:
        ybc_entries = parse_section("YBC", sections["YBC"])
        print(f"[DEBUG] YBC パース結果: {len(ybc_entries)} 件", file=sys.stderr)
        new_entries += ybc_entries
    else:
        print("[DEBUG] YBC セクションが見つかりませんでした", file=sys.stderr)

    # J1が見つかったのに0件だった場合、原因の切り分けのため内訳も出す
    if "J1" in sections and len(new_entries) == 0:
        plain = strip_tags(sections["J1"])
        rb = extract_round_date_blocks(plain)
        ib = extract_team_logo_images(sections["J1"])
        print(f"[DEBUG] J1内の「節・日付」ブロック数: {len(rb)}", file=sys.stderr)
        print(f"[DEBUG] J1内の「team_logo画像」タグ数: {len(ib)}", file=sys.stderr)
        print(f"[DEBUG] J1セクション冒頭300文字: {sections['J1'][:300]!r}", file=sys.stderr)

    # 天皇杯は「対戦相手未定」の間はスタジアム/HOME・AWAY表記が省略され
    # フォーマットが崩れやすいため自動パース対象から外し、既存データを保持する。

    if len(new_entries) < 30:
        # J1だけで38試合前後あるはずなので、極端に少ない場合はサイト構造の変化を疑い、
        # 既存ファイルを壊さないよう安全側に倒して終了する。
        print(f"[WARN] 取得できた試合数が少なすぎます（{len(new_entries)}件）。"
              f"サイト構造が変わった可能性があるため、schedule.json は更新しません。", file=sys.stderr)
        sys.exit(2)

    # 既存の schedule.json を読み込み、EMP・ACL2エントリーは保持したまま J1/YBC のみ差し替える
    if SCHEDULE_JSON.exists():
        existing = json.loads(SCHEDULE_JSON.read_text(encoding="utf-8"))
    else:
        existing = []
    kept_entries = [e for e in existing if e.get("comp") in ("EMP", "ACL2")]

    merged = new_entries + kept_entries
    merged.sort(key=lambda e: e["sort"])

    # jleague.jp の「戦績」表から消化済み試合のスコアを取得してマージする。
    # J1に限らず、天皇杯・ルヴァン・ACL2など、この表に載る大会はすべて対象にする
    # （日付が一致すれば反映するだけなので、大会を問わない）。
    # ここが失敗しても日程データ自体は活かしたいので、例外は握りつぶして続行する。
    scored_count = 0
    try:
        results_html = fetch_html(RESULTS_URL)
        results = parse_results(results_html)
        results_by_date = {r["sort"]: r for r in results}
        for m in merged:
            r = results_by_date.get(m["sort"])
            if r:
                m["played"] = True
                m["scoreZelvia"] = r["scoreZelvia"]
                m["scoreOpp"] = r["scoreOpp"]
                scored_count += 1
    except Exception as e:
        print(f"[WARN] 試合結果（スコア）の取得に失敗しました。日程のみ更新します: {e}", file=sys.stderr)

    SCHEDULE_JSON.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] schedule.json を更新しました（{len(merged)}件: "
          f"J1/YBC {len(new_entries)}件 + EMP/ACL2(保持) {len(kept_entries)}件 / "
          f"スコア反映 {scored_count}件）")


if __name__ == "__main__":
    main()
