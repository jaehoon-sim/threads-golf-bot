# threads-golf-bot

골프 콘텐츠를 매일 2~3회 Threads에 자동 발행하고, 일부 글에 쿠팡파트너스 링크를 붙여 수익을 내는 파이프라인.

## 구조

```
Claude 스케줄 작업 (매일 06:00 KST)
  ├ plan.py 로 오늘 쓸 주제 선정 (쿨다운·중복 제거) + 제휴 글 여부 판정
  ├ 트렌드 주제면 웹 검색으로 사실 확인
  ├ 슬롯별 본문 작성 → queue/*.json
  ├ render_card.py 로 이미지 카드 렌더 → assets/*.png
  └ git push
                    ↓
GitHub Actions (30분마다)
  ├ publish.py — 예약 시각이 된 항목만 골라 검증
  ├ Threads 컨테이너 생성 → 35초 대기 → 발행
  ├ 제휴 글이면 대가성 문구 + 상품 링크 답글을 코드가 조립해 첫 답글로 발행
  └ history/history.jsonl 기록 후 커밋
```

발행은 GitHub Actions가 담당한다. Claude가 도는 클라우드 환경에서는 `graph.threads.net`
과 쿠팡 도메인 접근이 네트워크 정책으로 차단되기 때문이고, 덕분에 액세스 토큰이 Claude
세션에 노출되지 않는다는 이점도 있다.

## 최초 설정

1. **Meta 앱 준비** — developers.facebook.com 에서 앱 생성 → Threads API 제품 추가 →
   `threads_basic`, `threads_content_publish` 권한 → 본인 계정을 테스터로 등록.
   본인 계정에만 발행한다면 앱 심사(App Review) 없이 개발 모드로 운영할 수 있다.
2. **장기 토큰 발급** — 앱 대시보드에 Redirect Callback URL 을 등록한 뒤, **본인 PC에서**
   `python3 scripts/get_token.py` 를 실행한다. 브라우저 인증 → 코드 교환 → 장기 토큰(60일)
   발급 → 사용자 ID 조회까지 한 번에 끝나고, GitHub Secrets 에 넣을 두 값을 출력한다.
   표준 라이브러리만 쓰므로 설치할 것은 없다.
3. **레포 생성** — 이 폴더를 **public** 레포로 push. 이미지가
   `raw.githubusercontent.com` 공개 URL 로 서빙되어야 Threads가 읽어간다.
4. **Secrets 등록** — Settings → Secrets and variables → Actions
   - `THREADS_USER_ID`
   - `THREADS_ACCESS_TOKEN`
   - `GH_PAT` (선택, 토큰 자동 갱신용 · secrets 쓰기 권한 fine-grained PAT)
5. **드라이런 확인** — Actions → publish-to-threads → Run workflow → dry_run 체크.
6. **Claude 스케줄 작업 등록** — `prompts/daily.md` 내용을 그대로 사용.

## 쿠팡파트너스 수익화

기본값은 꺼져 있다. 켜는 순서:

1. partners.coupang.com 가입. 운영 채널에 **이 스레드 계정 URL** 을 등록한다.
2. 쿠팡에서 상품을 골라 파트너스 링크를 만들고 `content/products.yaml` 에 채운다.
   `facts` 에는 상품 페이지에서 직접 확인한 사실만 적는다. 비어 있으면 그 상품은 쓰이지 않는다.
3. `content/topic_pool.yaml` 의 `monetization.enabled` 를 `true` 로 바꾼다.

이후는 자동이다. `plan.py` 가 빈도 조건을 따져 제휴 글을 낼 날을 고르고, Claude는 상품을
끝에 살짝 붙인 정보 글을 쓰고, `publish.py` 가 링크 답글을 붙여 발행한다.

| 설정 | 기본값 | 뜻 |
|---|---|---|
| `start_after_posts` | 20 | 일반 글이 이만큼 쌓이기 전에는 제휴 글 금지 |
| `max_per_week` | 3 | 최근 7일 제휴 글 상한 |
| `min_gap_days` | 2 | 제휴 글 사이 최소 간격 |
| `slot` | 21:00 | 제휴 글을 넣을 슬롯 |
| `product_cooldown_days` | 21 | 같은 상품 재추천 금지 기간 |

**코드로 막는 것** (완전 자동 발행이라 사람 대신 `publish.py` 가 거부한다)

- 제휴 글 본문이 `disclosure_short` 로 시작하지 않으면 발행 거부
- 본문·답글에 URL 이 직접 들어 있으면 거부. 링크는 `products.yaml` 에서만 꺼낸다
- 카탈로그에 없거나 비활성인 상품이면 거부
- 제휴 표시 없는 글에 쿠팡 링크가 섞여 있으면 거부
- 제휴 글의 카드 이미지에는 `광고 · 쿠팡파트너스` 표기가 자동으로 박힌다

거부된 항목은 `history.jsonl` 에 `invalid` 와 사유가 남는다.

## 로컬 명령

```bash
pip install -r scripts/requirements.txt && playwright install chromium

python scripts/plan.py --slots 3          # 오늘 쓸 주제 후보 + 제휴 글 여부
python scripts/render_card.py --all       # 큐 전체 이미지 렌더
DRY_RUN=1 python scripts/publish.py       # 발행 없이 검증·계획만 확인
```

## 큐 항목 형식

```json
{
  "id": "2026-08-25-0730",
  "scheduled_at": "2026-08-24T22:30:00+00:00",
  "topic_key": "short-game",
  "text": "본문 (500자 이내)",
  "topic_tag": "골프",
  "card": { "kicker": "PUTTING", "headline": "...", "body": "...", "tag": "#퍼팅", "handle": "@handle", "accent": "fairway" },
  "affiliate": { "product_key": "putting-mat-1", "blurb": "40자 이내 한 줄 소개" },
  "thread": ["이어지는 답글 (선택)"],
  "status": "pending"
}
```

- `id` 는 `YYYY-MM-DD-HHMM` (KST 발행 시각). 이미지 파일명과 1:1로 대응한다.
- `scheduled_at` 은 **UTC ISO8601**. KST에서 9시간을 뺀다.
- `card` 를 빼면 텍스트 전용 게시물이 된다.
- `affiliate` 는 제휴 글에만 넣는다. 예시는 `queue/_sample_affiliate.json.example`.
- 예약 시각을 90분 넘긴 항목은 발행하지 않고 만료 처리한다.

## 한계와 주의

- **완전 자동 발행**이므로 사실 오류가 그대로 나간다. `trend` 기둥은 웹 검색으로 확인된
  사실만 쓰도록 프롬프트에 못 박아 두었고, 확인이 안 되면 다른 기둥으로 대체한다.
- 대가성 문구 규정은 공정위 추천·보증 심사지침과 쿠팡파트너스 정책을 따른다. 정책이 바뀌면
  `monetization.disclosure*` 문구만 고치면 된다. 법률 자문은 아니다.
- 하루 발행 상한은 계정당 250건. 답글은 상한에 포함되지 않는다.
- 장기 토큰은 60일. `refresh-threads-token` 워크플로가 매월 1·15일에 갱신한다.
  `GH_PAT` 를 넣지 않으면 수동으로 재발급해야 한다.
- 이미지는 public 레포에 커밋된다. 비공개로 두려면 별도 CDN(R2, S3 등)이 필요하다.
