"""모의 CRM 서버 — 시연·개발용.

⚠️ 여기 데이터는 전부 **가짜**다. 실제 CRM이 아니다.
   시연 시 "CRM은 아직 연동 전이라 모의 서버로 대체했다"고 반드시 밝힐 것.

실 CRM API 스펙이 확정되기 전까지 이 서버로 대신한다.
어댑터(crm/client.py)가 HTTP를 그대로 타므로, 실 CRM으로 바꿀 때는
CRM_BASE_URL 한 줄만 교체하면 되고 애플리케이션 코드는 그대로다.

응답 형태는 사내 API에서 흔한 형태를 가정했다:
    GET  {base}/customers/{code}
    200  {"result": { ... }}      미등록이면 404

    python standalone/mock_crm.py [포트]
    python standalone/mock_crm.py 8900
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# 기획서 §5 화면 예시 + 기술지원 기획서에 등장하는 고객번호를 채워
# 두 시연이 같은 데이터로 이어지게 한다.
# 회사명은 기획서에 나온 그대로 두고, 담당자 연락처는 모두 가상 값이다.
CUSTOMERS = {
    "E230096": {
        "custNo": "E230096", "custType": "계약", "custName": "미래에셋자산운용",
        "deptName": "채권운용부문 투자전략본부", "userName": "정상호 매니저",
        "tel1": "02-3774-8013", "tel2": None,
        "email": "sanghojeong9210@miraeasset.com",
        "billingDate": "2023-05-01", "contractStartDate": "2023-05-01",
        "contractEndDate": "2024-04-30", "renewalStartDate": None,
        "installDate": "2023-02-13", "deviceType": "고객기기",
        "lineType": "고객회선", "lineType2": "사내-LAN(고정IP)", "carrier": None,
    },
    "E21016": {
        "custNo": "E21016", "custType": "계약", "custName": "비엔케이자산운용",
        "deptName": "운용지원팀", "userName": "김수빈 파트너",
        "tel1": "051-620-8100", "tel2": "010-1234-5678",
        "email": "subin.kim@example.co.kr",
        "billingDate": "2024-03-01", "contractStartDate": "2024-03-01",
        "contractEndDate": "2026-02-28", "renewalStartDate": "2026-01-01",
        "installDate": "2024-02-20", "deviceType": "고객기기",
        "lineType": "고객회선", "lineType2": "사내-LAN", "carrier": "KT",
    },
    "E200105": {
        "custNo": "E200105", "custType": "계약", "custName": "비엔케이자산운용",
        "deptName": "리스크관리팀", "userName": "박도현 대리",
        "tel1": "051-620-8210", "tel2": None,
        "email": "dohyun.park@example.co.kr",
        "billingDate": "2024-03-01", "contractStartDate": "2024-03-01",
        "contractEndDate": "2026-02-28", "renewalStartDate": None,
        "installDate": "2024-02-20", "deviceType": "연합기기",
        "lineType": "ADSL", "lineType2": "외부회선", "carrier": "SKT",
    },
    "E140605": {
        "custNo": "E140605", "custType": "계약", "custName": "에이치라인해운",
        "deptName": "자금기획팀", "userName": "이준호 과장",
        "tel1": "02-3702-1200", "tel2": None,
        "email": "junho.lee@example.co.kr",
        "billingDate": "2022-07-01", "contractStartDate": "2022-07-01",
        "contractEndDate": "2025-06-30", "renewalStartDate": None,
        "installDate": "2022-06-15", "deviceType": "고객기기",
        "lineType": "고객회선", "lineType2": "사내-LAN(고정IP)", "carrier": "LGU+",
    },
    "E050282": {
        "custNo": "E050282", "custType": "계약", "custName": "한국거래소",
        "deptName": "파생시장부(부산)", "userName": "김재영 차장",
        "tel1": "051-662-2635", "tel2": None,
        "email": "jaeyoung.kim@example.co.kr",
        "billingDate": "2021-01-01", "contractStartDate": "2021-01-01",
        "contractEndDate": "2026-12-31", "renewalStartDate": "2026-10-01",
        "installDate": "2020-12-10", "deviceType": "고객기기",
        "lineType": "고객회선", "lineType2": "사내-LAN(고정IP)", "carrier": "KT",
    },
    "E050102": {
        "custNo": "E050102", "custType": "시험", "custName": "한국거래소",
        "deptName": "파생시장부(부산)", "userName": "최재원 대리",
        "tel1": "051-662-2640", "tel2": None,
        "email": "jaewon.choi@example.co.kr",
        "billingDate": None, "contractStartDate": "2026-08-01",
        "contractEndDate": "2026-10-31", "renewalStartDate": None,
        "installDate": "2026-07-25", "deviceType": "연합기기",
        "lineType": "고객회선", "lineType2": "사내-LAN", "carrier": None,
    },
    "E050345": {
        "custNo": "E050345", "custType": "계약", "custName": "한국거래소",
        "deptName": "파생시장부(부산)", "userName": "이현석 수석",
        "tel1": "051-662-2651", "tel2": None,
        "email": "hyunseok.lee@example.co.kr",
        "billingDate": "2021-01-01", "contractStartDate": "2021-01-01",
        "contractEndDate": "2026-12-31", "renewalStartDate": None,
        "installDate": "2020-12-10", "deviceType": "고객기기",
        "lineType": "고객회선", "lineType2": "사내-LAN(고정IP)", "carrier": "KT",
    },
    # 해지 고객 — 고객구분이 다르게 보이는 케이스
    "E110220": {
        "custNo": "E110220", "custType": "해지", "custName": "대한선물",
        "deptName": "IT지원팀", "userName": "한지민 과장",
        "tel1": "02-6001-3300", "tel2": None,
        "email": "jimin.han@example.co.kr",
        "billingDate": "2019-04-01", "contractStartDate": "2019-04-01",
        "contractEndDate": "2025-03-31", "renewalStartDate": None,
        "installDate": "2019-03-20", "deviceType": "고객기기",
        "lineType": "ADSL", "lineType2": "외부회선", "carrier": "SKT",
    },
}

# 지연 시연용 — 이 코드로 조회하면 응답이 늦어 타임아웃 안내가 나온다
SLOW_CODE = "E999998"
SLOW_SECONDS = 5


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = self.path.rstrip("/").rsplit("/", 1)[-1].split("?")[0]

        if code == SLOW_CODE:
            print(f"  [{_now()}] {code} → 지연 시뮬레이션 {SLOW_SECONDS}초")
            time.sleep(SLOW_SECONDS)

        row = CUSTOMERS.get(code)
        if row is None:
            print(f"  [{_now()}] {code} → 404 미등록")
            self._send(404, {"header": {"resultCode": 404, "resultMessage": "not found"}})
            return

        print(f"  [{_now()}] {code} → 200 {row['custName']}")
        self._send(200, {"header": {"resultCode": 0, "resultMessage": ""}, "result": row})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass        # 기본 접근 로그는 끈다 (위에서 직접 찍는다)


def _now() -> str:
    return time.strftime("%H:%M:%S")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
    server = HTTPServer(("127.0.0.1", port), Handler)

    print("=" * 58)
    print("  모의 CRM 서버 — 시연·개발용 (실제 CRM 아님)")
    print("=" * 58)
    print(f"  http://127.0.0.1:{port}/customers/{{고객번호}}")
    print(f"  등록된 고객번호 {len(CUSTOMERS)}건:")
    for code, row in CUSTOMERS.items():
        print(f"    {code:9} {row['custName']} ({row['custType']})")
    print(f"    {SLOW_CODE:9} (지연 {SLOW_SECONDS}초 — 타임아웃 시연용)")
    print()
    print("  에이전트 설정:")
    print(f"    CRM_BASE_URL=http://127.0.0.1:{port}")
    print("=" * 58)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
