# coding: utf-8

# 언어팩 정보
PARM_TYPE = 0 # 0:통상 1:P계약자용(단일서버) 2:P계약자용(복수서버) 3:수주계약자용
PARM_TITLE = '기본 언어팩'
PARM_DESC = '유나봇의 기본 언어팩입니다. 모두에게 사근사근하면서 어딘가 나긋한 성격인 치쿠마 유나를 최대한 구현…할 수 있었으면 하토가 소설을 몇 번씩 탈고했는데도 만족을 못 해서 결국엔 버리지 않았겠죠? (실제로 Dream Collector 0~3화는 2018년 6월부터 지금(2026년 5월)까지 14번째 탈고 중)'


# 변수는 {변수명} 으로 사용하실 수 있습니다.
# 앞에 (필수)라고 붙은 변수가 아닌 이상, 전부 선택입니다.
# 아래의 언어팩은 '항목 이름':'대사' 형식으로 이루어져 있습니다. 항목 이름은 절대로 바뀌면 안 됩니다. 대사는 : 뒤쪽에 입력해 주세요. 또한, 각 항목 뒤엔 쉼표(,)가 있어야 합니다.
#
# [문구 배치 규칙]
# - onboarding(초기설정), setting 중 애드온 외 항목 → 이 파일(default.py)에만 추가
# - 애드온 전용 설정 문구는 해당 애드온 톤 파일에만 추가
# - 위 문구는 서버 tone_profile이 아닌 default(애드온 봇은 boot addon tone)에서만 조회합니다.

# 언어팩 내용
LANG_PACK = {
    ##### 활동 경험치 #####

    #### A. 출석체크 콜백 ####
    # 출석체크는 하루 한 번, 첫 번째 채팅을 전송하면 자동으로 완료됩니다. 출석체크가 완료되었을 때 지정한 채널로 전송할 채팅입니다. (전송을 하지 않게 설정할 수도 있습니다.)
    # 변수
    # * {author} : 유저 표시 이름 (username) — 예: 하토 (hanamuke_no_hanataba)
    # * {d_arg} : 해당 유저가 며칠만에 다시 찾아왔는지 (예를 들어 하루만에 찾아왔으면 1, 3일만에 찾아왔으면 3)
    # 위치 : c_expFE > on_message

    # 출석체크가 정상적으로 완료되었을 때 전송할 채팅
    # 유나봇은 사용자가 며칠만에 다시 찾아왔는지(d_arg)에 맞춰 출석체크 메세지를 보내는 기능이 있습니다. 메세지 갯수, 날짜 범위 등을 자유롭게 설정하실 수 있도록, 해당 항목을 이중 리스트로 구성하게 되었습니다.
    # 형식 : [기준 일수(설명 참고), 제목, 내용]이 있는 이중 리스트
    # 기준 일수는 무조건 오름차순으로 작성해야 합니다.
    # 첫 줄부터 순서대로 검사하면서, 처음으로 d_arg보다 크거나 같은 기준 일수가 나온 줄의 대사를 전송합니다. (만약 끝까지 돌았는데도 조건에 맞는 기준 일수가 나오지 않았다면 마지막 줄의 대사를 전송)
    # 예시 : [[1, '테스트1',''],[4,'테스트2',''],[10,'테스트3',''],[None,'테스트4','']]
    # 하루만에 왔을 때   : 테스트1
    # 2~4일만에 왔을 때  : 테스트2
    # 5~10일만에 왔을 때 : 테스트3
    # 11~일만에 왔을 때  : 테스트4
    # 마지막 줄은 날짜 범위를 None으로 입력하는 것을 권장합니다.
    # 변수
    # * {author} : 유저 표시 이름 (username) — 예: 하토 (hanamuke_no_hanataba)
    # * {d_arg} : 해당 유저가 며칠만에 다시 찾아왔는지
    # * {day_count} : 총 출석 일수
    'expFE_res_daily':[
        [1,'{author}님, 오늘도 오셨네요!','자동으로 {day_count}번째 출석이 완료되었어요.'],
        [2,'{author}님, 어제는 바쁜 일이 있으셨나요?','우리 서버를 이틀만에 찾아주셨어요. 자동으로 {day_count}번째 출석이 완료되었어요.'],
        [5,'{author}님, 어서 오세요!','우리 서버를 {d_arg}일만에 찾아주셨어요. 자동으로 {day_count}번째 출석이 완료되었어요.'],
        [None,'{author}님, 오랜만이네요.','우리 서버를 {d_arg}일만에 찾아주셨어요. 자동으로 {day_count}번째 출석이 완료되었어요.']
    ],

    # 맨 처음 회원가입(경험치 DB 신규 등록) 시 출석 알림 채널로 보내는 환영 임베드
    # 변수
    # * {author} : 유저 표시 이름 (username)
    # * {bot_name} : 봇 이름
    'expFE_res_welcome_title':'{author}님, 환영합니다!',
    'expFE_res_welcome_desc':'{bot_name}에 회원가입되었어요! 이제부터 {author}님의 채팅 횟수와 통화 시간을 집계해서 활동 경험치로 바꿔드릴게요.\n5시 15분부터 다음날 5시 14분 59초까지 한 번이라도 채팅을 보내시거나 15초 이상 통화하시면 자동으로 출석돼요. `/출석` 명령어를 사용해서 출석할 수도 있어요.',

    #### B. 경험치 슬래시 명령어 ####
    # 설정에 표시되는 설명입니다.
    'expFE_group_name':'활동 경험치 기능 관련 명령어에요. (현황, 랭킹 등)',

    #### C. 경험치 현황 ####
    # /경험치 현황 명령어의 설명입니다.
    'expFE_status_desc':'경험치 현황을 확인할 수 있어요.',

    # /경험치 현황 명령어를 입력했을 때, 해당 명령어의 답장으로 전송될 채팅(embed)입니다.
    # 제목과 필드(등록일자, 출석일수, 통화 시간, 채팅 개수), 설명(레벨 진행도)으로 이루어져 있습니다.
    # 변수
    # * {display} : 해당 유저의 닉네임 (예시 : 하토)
    # * {username} : 해당 유저의 username (예시 : hanamuke_no_hanataba)
    # * {author} : 표시 이름 (username) 결합형 — 예: 하토 (hanamuke_no_hanataba) (하위 호환)
    # * (필수) {exp} : 해당 유저의 경험치
    # * {exp_incr} : 해당 유저의 경험치 증가분
    'expFE_status_embed_title':'{display} ({username}) 님의 활동 경험치는 {exp} (▲ {exp_incr})(이)에요.',
    'expFE_status_embed_field1':'우리 서버와 함께하기 시작한 날',
    'expFE_status_embed_field2':'출석 일수',
    'expFE_status_embed_field3':'통화 시간',
    'expFE_status_embed_field4':'채팅 개수',

    # '유나봇과 함께 하기 시작한 날'이 없는 경우
    'expFE_status_embed_field1_nodata':'(회원가입 전 - 아무 채팅이나 입력해 주세요)',

    # '유나봇과 함께 하기 시작한 날'
    # 변수: year, month, day, hour, minute, second
    'expFE_status_embed_field1_value':'{year}년 {month}월 {day}일 {hour}시 {minute}분 {second}초',

    # '유나봇과 함께한 나날 (출석 일수)'
    # 변수 : (필수) {day_count} : 출석일수
    'expFE_status_embed_field2_value':'{day_count}일',

    # '채팅 갯수'
    # 변수
    # * (필수) {total} : 전체 채팅 갯수
    # * {count} : 점수로 집계된 채팅 갯수
    'expFE_status_embed_field4_value':'총 {total}개 (중 집계 대상 채팅 {count}개)',
    # '레벨'
    # 변수
    # * (필수) {level} : 현재 레벨
    # * (필수) {pct} : 현재 레벨 진행도(소수 첫째 자리 %)
    # * (필수) {into} : 현재 레벨 구간에서 누적한 경험치
    # * (필수) {span} : 현재 레벨 구간 전체 경험치
    # * (필수) {need} : 다음 레벨까지 남은 경험치
    'expFE_status_embed_field_level_value':'Lv.{level} {pct}% [{into}/{span}] 다음 레벨까지 {need}',

    # '통화 시간' 표기 — expFE_voice_duration_form 참고
    # True: 아래 unit tone(시간/분/초)을 공백으로 조합. False: 1:02:03.4 형식 (항상 H:MM:SS.t, 0초는 0:00:00.0)
    'expFE_voice_duration_form': True,
    'expFE_voice_duration_zero':'0초', #시간이 없는 경우 (form=True 일 때만)
    'expFE_voice_unit_hour':'{value}시간', #1시간 (60분 미만인 경우 표시 X)
    'expFE_voice_unit_minute':'{value}분', #2분 (60초 미만인 경우 표시 X)
    'expFE_voice_unit_second':'{value}초', #3초, 3.4초 등

    #### D. 경험치 랭킹(채팅) ####
    # /경험치 랭킹 명령어의 설명과 옵션입니다.
    'expFE_ranking_desc':'경험치 랭킹을 볼 수 있어요.',
    'expFE_ranking_web_notice':'경험치 랭킹은 아래 웹사이트에서 확인할 수 있어요.',
    'expFE_ranking_web_button':'랭킹 페이지 열기',
    'expFE_ranking_option1_name':'종류',
    'expFE_ranking_option1_desc':'누적 순위를 표시할 지, 아니면 오늘/어제 얻은 경험치 순위를 표시할 지 선택해 주세요.',
    'expFE_ranking_option1_choice0':'누적 순위',
    'expFE_ranking_option1_choice1':'오늘 순위',
    'expFE_ranking_option1_choice2':'어제 순위',
    'expFE_ranking_option2_name':'페이지',
    'expFE_ranking_option2_desc':'몇 페이지를 표시할지 입력해주세요. (한 페이지에 20명)',
    'expFE_ranking_waiting':'> ⌛ 지금 경험치 랭킹을 집계하는 중이에요. 시간이 걸릴 수 있으니 잠시만 기다려주세요.',

    # 랭킹 결과
    # 랭킹 맨 위에 표시되는 메세지입니다.
    # 변수
    # * {guild_name} : 길드명
    # * {kind} : 랭킹 종류 (누적/오늘/어제)
    # * {page} : 현재 페이지
    # * {total_pages} : 총 페이지
    'expFE_ranking_result_header':'{guild_name}의 {kind} 경험치 랭킹 현황이에요. ({page}/{total_pages} 페이지)',

    # 해당 페이지에 표시할 멤버가 없는 경우 (총 페이지 범위를 초과한 경우)
    'expFE_ranking_result_nomember':'(해당 페이지에 표시할 멤버가 없어요.)',

    # 각 줄의 형식
    # expFE_ranking_result_leaved는 탈퇴한 유저의 닉네임 뒤에 붙는 문구?입니다.
    # 변수
    # * {rank} : 순위
    # * {display} : 해당 유저의 닉네임 (예시 : 하토)
    # * {username} : 해당 유저의 global name (예시 : soramehato / 하토#6967)
    # * {score} : 현재 경험치
    # * {delta} : 오늘 경험치 증가분
    'expFE_ranking_result_line':'{rank}위 : {display} ({username}) {score} (▲ {delta})',
    'expFE_ranking_result_leaved':'(탈퇴)',

    # 인터렉션이 중간에 닫힌 경우
    # 변수 : {id} : 요청한 사람의 ID
    'expFE_ranking_interaction_closed':'<@{id}>인터렉션이 중간에 닫혀 별도의 채팅으로 보냈어요.',

    # 랭킹 페이지 버튼
    'expFE_ranking_btn_prev':'이전',
    'expFE_ranking_btn_next':'다음',
    'expFE_ranking_btn_denied':'본인이 요청한 랭킹만 페이지를 넘길 수 있어요.',

    #### E. 경험치 멘션 ####
    # /경험치 멘션 명령어를 입력했을 때, 해당 명령어의 답장으로 전송될 채팅입니다.
    # 변수 : {result} : changeSilentStatus의 반환값

    # 해당 명령어의 설명
    'expFE_mention_desc':'출석 체크 시의 멘션을 켜고 끌 수 있어요.',
    'expFE_mention_option_name':'여부',
    'expFE_mention_option_desc':'출석 체크 할 때 멘션을 보낼까요?',
    'expFE_mention_option_choice_on':'보내기',
    'expFE_mention_option_choice_off':'보내지 않기',

    # 성공적으로 켜고 껐을 때
    'expFE_mention_on':'앞으로 출석 체크할 때 멘션을 보낼게요.',
    'expFE_mention_off':'앞으로 출석 체크할 때 멘션을 보내지 않을게요.',

    # 오류가 발생했을 때
    'expFE_mention_error':'DB에 오류가 발생해서 설정을 바꿀 수 없었어요.',

    #### F. 수동 출석 ####
    # /출석 명령어의 설명입니다.
    'expFE_attend_desc':'수동으로 출석할 수 있어요.',

    # 이미 오늘 출석이 완료된 경우
    'expFE_attend_already':'오늘은 이미 출석되었어요.',

    # 경험치 기능이 꺼져 있거나 대상이 아닌 경우
    'expFE_attend_unavailable':'지금은 출석할 수 없어요. 경험치 기능이 켜져 있는지 확인해주세요.',

    ##### 예약메세지 #####

    #### A. 알림 슬래시 명령어 ####
    # 설정에 표시되는 설명입니다.
    'dailyInform_weekdays_label': '보낼 요일 (여러개 선택 가능)',
    'dailyInform_date_label_monthly': '보낼 날짜 (매월 ○○일에 전송)',
    'dailyInform_date_label_yearly': '보낼 날짜 (매년 ○○월 ○○일에 전송)',
    'dailyInform_date_label_once': '보낼 날짜',
    'dailyInform_date_placeholder_monthly': '숫자만 입력(1~31) / 해당 날짜가 없는 달에는 말일에 전송합니다.',
    'dailyInform_date_placeholder_yearly': '예: 1031, 10-31, 10/31, 10.31 (한 자리 월·일도 가능)',
    'dailyInform_date_placeholder_once': '예: 20271031, 2027-10-31, 2027/10/31, 2027.10.31.',
    'dailyInform_schedule_daily': '매일 {time}',
    'dailyInform_schedule_weekly': '매주 {weekdays} {time}',
    'dailyInform_schedule_monthly': '매월 {day}일 {time}',
    'dailyInform_schedule_yearly': '매년 {month}월 {day}일 {time}',
    'dailyInform_schedule_once': '{year}년 {month}월 {day}일 {time}',
    'dailyInform_invalid_schedule_daily': '전송 주기를 다시 선택해 주세요.',
    'dailyInform_invalid_schedule_weekly': '발송할 요일을 1~7개 선택해 주세요.',
    'dailyInform_invalid_schedule_monthly': '보낼 날짜를 1~31 사이에서 숫자만 입력해 주세요.',
    'dailyInform_invalid_schedule_yearly': '실제로 존재하는 월·일을 입력해 주세요. 예: 1031, 10-31, 10/31, 10.31',
    'dailyInform_invalid_schedule_once': '실제로 존재하는 연·월·일을 입력해 주세요. 예: 20271031, 2027-10-31, 2027/10/31, 2027.10.31.',
    'dailyInform_once_past': '과거로 메시지를 보낼 수는 없어요. 미래의 날짜/시간을 입력해주세요.',
    'dailyInform_weekday_0': '월요일',
    'dailyInform_weekday_1': '화요일',
    'dailyInform_weekday_2': '수요일',
    'dailyInform_weekday_3': '목요일',
    'dailyInform_weekday_4': '금요일',
    'dailyInform_weekday_5': '토요일',
    'dailyInform_weekday_6': '일요일',
    'dailyInform_group_desc':'예약메세지를 관리하는 명령어에요.',
    'dailyInform_period_option_name':'주기',
    'dailyInform_add_period_desc':'메세지 전송 주기를 선택해 주세요.',
    'dailyInform_edit_period_desc':'주기를 변경하고 싶으시면 이 옵션에서 변경할 주기를 선택해 주세요.',
    'dailyInform_period_choice_daily':'매일',
    'dailyInform_period_choice_weekly':'매주',
    'dailyInform_period_choice_monthly':'매월',
    'dailyInform_period_choice_yearly':'매년',
    'dailyInform_period_choice_once':'1회',

    #### B. 등록 ####
    # 알림을 등록하는 기능이에요.
    # 변수
    # * {time} : 보낼 시간
    # * {message} : 보낼 메세지

    # /알림 등록 명령어의 설명과 옵션
    'dailyInform_add_desc':'예약메세지를 등록할 수 있어요.',
    'dailyInform_add_option1_name':'시간',
    'dailyInform_add_option1_desc':'메세지를 보낼 시간을 입력해주세요. 예: 10시 31분, 15시 반, 23시, 11:03, 1031',
    'dailyInform_add_option_message_name':'메세지',
    'dailyInform_add_option_message_desc':'전송할 메세지를 입력해주세요.',
    'dailyInform_modal_title':'메세지 등록',
    'dailyInform_modal_edit_title':'메세지 수정',
    'dailyInform_modal_delete_title':'메세지 삭제',
    'dailyInform_modal_field_time_label':'시간',
    'dailyInform_modal_field_time_placeholder':'예: 10시 31분, 15시 반, 23시, 11:03',
    'dailyInform_modal_field_message_label':'메세지',
    'dailyInform_modal_field_message_placeholder':'전송할 메세지를 입력해 주세요.',
    'dailyInform_modal_field_channel_label':'채널',
    'dailyInform_modal_field_channel_placeholder':'전송할 채널을 선택해 주세요.',
    # 메세지 등록에 성공한 경우
    'dailyInform_add_success':'{time}에 \'{message}\' 라고 전송할게요.',

    #### C. 조회 ####
    # 등록된 알림을 조회하는 기능이에요.

    # /알림 조회 명령어의 설명과 옵션
    'dailyInform_list_desc':'등록된 예약메세지를 조회할 수 있어요.',
    'dailyInform_list_option1_name':'페이지',
    'dailyInform_list_option1_desc':'몇 페이지를 표시할지 입력해주세요. (한 페이지에 5개)',

    # 응답
    # 변수
    # * {page} : 현재 페이지
    # * {total} : 전체 알림 갯수
    # * {start} : 범위 시작
    # * {end} : 범위 종료
    # * {order} : 목록 순번 (시간 > ID 순)
    # * {id} : 알림 ID
    # * {message} : 메세지
    # * {time} : 보낼 시간

    # 등록된 알림이 없는 경우
    'dailyInform_list_empty':'이 서버에는 등록된 메세지가 없어요.',
    # 해당 페이지엔 출력할 알림이 없는 경우
    'dailyInform_list_page_empty':'{page}페이지엔 출력할 메세지가 없어요.',
    # 결과가 있는 경우
    'dailyInform_list_header':'총 {total}개 중 {start}~{end}번째에요. ({page}/{total_pages} 페이지)',
    'dailyInform_list_btn_prev':'이전',
    'dailyInform_list_btn_next':'다음',
    'dailyInform_list_btn_denied':'본인이 요청한 알림 목록만 페이지를 넘길 수 있어요.',
    # 각 줄의 형식
    # * {authors} : 등록자(및 관리자 편집 시 편집자) 멘션 (<@id>)
    'dailyInform_list_line':'{order}. {message} ({time}, ID : {id}, {authors})',
    'dailyInform_list_authors_only':'등록자 : {author}',
    'dailyInform_list_authors_with_editor':'등록자 : {author}, 편집자 : {editor}',

    #### D. 시간/메세지 변경 ####
    # /알림 수정 명령어의 설명과 옵션
    'dailyInform_edit_desc':'등록된 메세지를 수정할 수 있어요.',
    'dailyInform_edit_option_name':'메세지',
    'dailyInform_edit_option_desc':'수정할 메세지를 선택해 주세요.',

    # 응답
    # 변수
    # * {message} : 기존 메세지
    # * {time} : 기존 시간
    # * {new_message} : 변경할 메세지
    # * {new_time} : 변경할 시간
    'dailyInform_edit_success':'이제 {time}에 {channel}으로 \'{message}\' 라고 전송할게요.',

    #### E. 메세지 삭제 ####
    # /알림 삭제 명령어의 설명과 응답
    'dailyInform_delete_desc':'등록된 메세지를 삭제할 수 있어요.',
    'dailyInform_delete_option_name':'메세지',
    'dailyInform_delete_option_desc':'삭제할 메세지를 선택해 주세요.',

    # 응답
    # 변수
    # {time} : 시간
    # {message} : 메세지
    'dailyInform_delete_confirm':'앞으로 원래 {time}에 보내기로 되어 있던 \'{message}\' 메세지를 보내지 않을까요? 되돌릴 수 없으니 신중하게 결정해주세요.',
    'dailyInform_delete_success':'이제 \'{message}\' 메세지는 보내지 않을게요.',

    #### F. 공통적으로 사용하는 항목 ####
    # 버튼 텍스트
    'dailyInform_btn_edit':'수정',
    'dailyInform_btn_delete':'삭제',

    # 이미 삭제된 경우
    'dailyInform_confirm_already_deleted':'이미 삭제된 메세지예요.',
    # 이미 해당 시간에 등록된 메세지가 있는 경우
    # {time} : 시간
    'dailyInform_add_duplicate':'이미 {time}엔 등록된 메세지가 있어요.',
    # 시간이 올바르지 않은 경우
    'dailyInform_invalid_time':'시간 형식이 올바르지 않아요. 예: 10시 31분, 15시 반, 20시 정각, 23시, 11:03, 1031',
    # ID가 잘못된 경우
    'dailyInform_not_found':'해당 ID의 메세지를 찾을 수 없어요.',
    # 권한이 없는 경우
    # {owner} : 해당 메세지를 등록한 사람
    # {verb} : 수행하려고 했던 작업 목록 (수정, 삭제 등)
    'dailyInform_perm_denied':'이 메세지는 {owner}님과 관리자만 {verb}할 수 있어요.',

    # 위의 {time} 등에 표시할 시간 형식
    'dailyInform_time_text':'{hour}시 {minute}분',
    # 디코 계정을 지웠거나 어떠한 이유로 메세지를 등록한 사람을 획득하지 못한 경우
    'dailyInform_author_unknown':'알 수 없는 등록자',
    # 그래도 ID는 알 수 있는 경우
    'dailyInform_author_id':'ID {author_id}',

    #### G. 예약 메시지 전송 실패 알림 ####
    # 변수
    # * {guild_name} : 서버 이름
    # * {channel_id} : 채널 ID
    # * {reason} : 실패 사유 (아래 reason 키로 치환된 문구)
    'dailyInform_send_failure':'[dailyInform] 서버 {guild_name}에서 예약된 메시지를 채널 <#{channel_id}>(ID : {channel_id})에 전송하지 못했습니다. 사유: {reason}. 채널이 삭제되었거나 봇 권한이 부족할 수 있습니다.',
    # 변수 : {detail} : 상세 오류 내용
    'dailyInform_send_failure_detail':' 상세: {detail}',
    'dailyInform_fail_reason_fetch_forbidden':'채널 조회 권한 없음',
    'dailyInform_fail_reason_channel_not_found':'채널 없음',
    'dailyInform_fail_reason_send_forbidden':'전송 권한 없음',
    # 길드명을 알 수 없는 경우
    'dailyInform_guild_unknown':'ID {unknown_id}',

    ##### 정보 #####
    # 봇 이름 (render_default_name)
    'bot_name':'유나봇',
    # {bot_name} : 봇 이름, {ver} : 봇 버전 (embed_footer)
    'embed_footer':'{bot_name} 버전 {ver}',
    # {bot_name} : 봇 이름
    # /정보 명령어 설명
    'info_command_desc':'봇 정보를 확인할 수 있어요.',
    # 응답
    # {bot_name} : 봇 이름
    'info_response_title':'{bot_name}의 정보에요.',
    # {ver} : 봇 버전, {addon} : 애드온 봇일 때 info_response_addon 문구 (아니면 빈 문자열)
    'info_response_desc':'버전 {ver}{addon}',
    # {addon_no} : 애드온 번호 (애드온 봇일 때만 사용)
    'info_response_addon':'\n유나봇 기반 서버 전용 봇 No. {addon_no}',
    'info_response_field1_title':'봇이 시작된 시각',
    # {loaded_time} : 봇이 시작된 시각 (bot.loadedTime)
    'info_response_field1_value':'{loaded_time}',
    'info_response_field2_title':'개발자',
    'info_response_field2_value':'소라메 하토 (SorameHato@protonmail.ch)',

    # 오류가 발생한 경우
    'error_title':'아무래도 바보토끼가 또 바보토끼 한 것 같아요. 하토를 불러주세요!',
    'error_embed_title':'자세한 내용',
    'error_embed_field1':'보낸 분',
    'error_embed_field2':'보낸 명령어',
    'error_embed_field2_unknown':'(알 수 없음)',
    'error_embed_photo':'https://amene.co/lapis10.png',
    # Discord가 이미 막거나, ephemeral/모달 소유자라 거의 보이지 않는 유효성 검사
    # 변수: {file} Cog/Addon 파일명, {func} 함수명, {reason} 이유
    'validation_error':'유효성 오류가 발생했어요. 파일 : {file}, 함수 : {func}, 이유 : {reason}',

    ##### 인증 #####
    # /인증 명령어 그룹
    'verify_group_desc':'가입 신청 기능을 관리할 수 있어요.',
    'verify_post_panel_desc':'가입 신청 안내 메세지를 보내거나 갱신해요. (관리자 전용)',
    'verify_post_panel_option_channel_name':'채널',
    'verify_post_panel_option_channel_desc':'가입 신청 안내 메세지를 보낼 채널 (선택)',

    # 패널·버튼
    'verify_panel_text':'가입 절차를 시작하시려면 아래의 `가입 신청` 버튼을 눌러 주세요.',
    'verify_btn_apply':'가입 신청',
    'verify_btn_approve':'승인',
    'verify_btn_reject':'거절',
    'verify_btn_thread_delete':'스레드 삭제',

    # 신청 모달
    'verify_modal_title':'서버 가입 신청',
    'verify_modal_answer_label':'답변',
    'verify_modal_answer_placeholder':'질문을 읽고 답변을 작성해 주세요.',
    'verify_modal_answer_description':'질문을 읽고 답변을 작성해 주세요.',
    'verify_question_empty':'(질문 없음)',

    # 검토 카드 임베드
    'verify_review_title':'가입 신청이 들어왔습니다.',
    'verify_review_field_applicant':'신청자',
    'verify_review_field_question':'질문',
    'verify_review_field_answer':'답변',
    'verify_review_field_status':'상태',
    'verify_review_field_reviewer':'처리자',
    'verify_review_field_decision':'처리 결과',
    'verify_review_footer':'신청 ID: {request_id}',
    'verify_review_applicant_unknown':'알 수 없음 ({user_id})',
    'verify_review_no_answer':'(답변 없음)',
    'verify_status_pending':'대기',
    'verify_status_approved':'승인',
    'verify_status_rejected':'거절',
    'verify_status_invalid_reapply':'무효(재신청)',
    'verify_invalidate_decision_note':'신청자가 새 신청을 제출하여 이 카드는 무효화되었어요.',

    # 처리 결과 메모
    'verify_decision_approved':'승인 처리되어 인증 완료 역할을 부여했어요.',
    'verify_decision_auto_reject_wrong':'정답이 있는 질문에서 오답이 확인되어 자동 거절 처리했어요.',
    'verify_decision_dm_sent':'거절 안내 DM 전송 완료',
    'verify_decision_dm_failed':'DM 전송 실패(무시)',
    'verify_decision_dm_skipped':'DM 전송 시도 후 무시됨',
    'verify_decision_kick_done':'킥 처리됨',
    'verify_decision_kick_failed':'킥 실패: {detail}',
    'verify_decision_kick_not_in_guild':'이미 서버에 없음',
    'verify_dm_reject':'안녕하세요? **{guild_name}** 서버의 가입 신청이 거절되어 퇴장 처리되었음을 알려드립니다.',
    'verify_role_reason_approve':'가입 승인',
    'verify_role_reason_reject':'가입 거절',
    'verify_thread_permission_reason':'인증 검토 스레드 채팅 권한',
    'verify_thread_completed_notice':'처리가 완료되었습니다. 이 스레드를 삭제하시려면 아래의 버튼을 눌러주세요.',
    'verify_thread_delete_done':'비공개 스레드를 삭제했어요.',
    'verify_thread_delete_failed':'스레드 삭제에 실패했어요: {detail}',

    # 응답 메시지
    'verify_perm_denied':'이 기능은 서버 관리자 또는 봇 관리 역할이 있어야 사용할 수 있어요.',
    'verify_premium_denied':'이 서버에서는 사용할 수 없는 프리미엄 기능이에요.',
    'verify_settings_load_failed':'인증 설정을 불러오는 중 오류가 발생했어요.',
    'verify_feature_disabled':'인증방 기능이 비활성화되어 있어요. `/설정`에서 먼저 활성화해 주세요.',
    'verify_cooldown':'최근 거절 이력이 있어요. {remain} 뒤에 다시 신청해 주세요.',
    'verify_cooldown_remain':'{minutes}분 {seconds}초',
    'verify_question_not_set':'아직 질문이 설정되지 않았어요. 관리자에게 문의해 주세요.',
    'verify_log_channel_not_set':'인증방 검토 로그 채널이 설정되지 않았어요. 관리자에게 문의해 주세요.',
    'verify_log_channel_not_found':'인증방 검토 로그 채널을 찾을 수 없어요.',
    'verify_log_channel_issue':'인증방 로그 채널을 사용할 수 없어요.\n{issue}',
    'verify_apply_submit_failed':'가입 신청 접수 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.',
    'verify_apply_submitted':'가입 신청이 접수되었어요. 관리자가 확인할 때까지 잠시만 기다려 주세요.',
    'verify_apply_partial_saved':'답변이 저장되었어요. 아래 버튼을 눌러 다음 질문으로 넘어가 주세요.',
    'verify_btn_apply_continue':'다음 질문',
    'verify_apply_continue_expired':'이어하기 버튼이 만료되었어요. 인증 신청을 다시 시작해 주세요.',
    'verify_auto_reject_wrong_answer':'정답이 있는 질문에서 오답이 확인되어 신청이 거절되었어요. 답변을 확인한 뒤 다시 신청해 주세요.',
    'verify_review_message_not_found':'처리할 신청서를 찾을 수 없어요.',
    'verify_application_not_found':'신청서 데이터를 찾을 수 없어요.',
    'verify_application_already_processed':'이미 처리된 신청서예요.',
    'verify_role_not_set':'인증 완료 역할이 설정되지 않았어요. `/설정`에서 먼저 지정해 주세요.',
    'verify_role_not_found':'설정된 인증 완료 역할을 찾을 수 없어요.',
    'verify_bot_no_manage_roles':'봇에 역할 관리 권한이 없어서 승인할 수 없어요.',
    'verify_bot_role_too_low':'봇 역할이 인증 완료 역할보다 낮아서 역할을 부여할 수 없어요.',
    'verify_applicant_not_in_guild':'신청자가 현재 서버에 없어 승인할 수 없어요.',
    'verify_role_grant_failed':'역할 부여에 실패해서 승인할 수 없어요: {detail}',
    'verify_decision_failed':'신청서 처리에 실패했어요.',
    'verify_review_edit_failed':'처리는 완료됐지만 신청서 메시지 갱신에 실패했어요.',
    'verify_post_panel_channel_required':'인증 메세지 채널을 선택해 주세요.',
    'verify_post_panel_channel_issue':'선택한 채널에 인증 메세지를 게시할 수 없어요.\n{issue}',
    'verify_post_panel_success':'가입 신청 안내 메세지를 {channel} 채널에 게시했어요.',
    'verify_btn_thread':'비공개 스레드',
    'verify_grade_status_descriptive':'Q{index}: 서술형',
    'verify_grade_status_correct':'Q{index}: 정답',
    'verify_grade_status_wrong':'Q{index}: 오답',
    'verify_grade_field_name':'자동 채점',
    'verify_repass_success':'이전에 가입을 승인한 적이 있는 신청자라서 프리패스로 통과 처리했어요.',
    'verify_auto_approve_all_correct':'모든 문제를 맞춰 자동으로 가입 승인 처리했어요.',
    'verify_review_panel_channel_not_set':'인증방이 설정되지 않았거나 찾을 수 없어요.',
    'verify_review_panel_channel_issue':'인증방을 사용할 수 없어요.\n{issue}',
    'verify_review_thread_name':'인증-{user_id}',
    'verify_review_thread_intro':'가입 신청 검토 스레드입니다.\n신청자: <@{user_id}>\n검토 카드: {review_link}',
    'verify_thread_create_done':'비공개 스레드를 만들었어요: {thread}',
    'verify_thread_create_failed':'스레드 생성 실패: {detail}',

    ##### 파티 #####
    # 위치: Cogs/c_party.py
    'party_group_desc':'파티 모집을 시작하거나 종료할 수 있어요.',
    'party_recruit_desc':'새 파티 모집을 시작할 수 있어요.',
    'party_modal_title':'파티 모집 시작',
    'party_modal_edit_title':'파티 모집 수정',
    'party_modal_field_title_label':'제목',
    'party_modal_field_title_placeholder':'모집 글의 위쪽에 표시될 제목을 입력해 주세요.',
    'party_modal_field_slots_label':'인원수',
    'party_modal_field_slots_placeholder':'예시 : 4',
    'party_modal_field_duration_label':'시간',
    'party_modal_field_duration_placeholder':'예시 : 2시간 30분',
    'party_modal_field_thread_label':'비공개 스레드',
    'party_modal_field_thread_placeholder':'선택해 주세요',
    'party_modal_field_thread_description':'모집 종료 후 비공개 스레드를 만들지 선택해 주세요.',
    'party_modal_field_thread_current_create':'현재 설정: 만들기 (선택하지 않으면 유지돼요)',
    'party_modal_field_thread_current_skip':'현재 설정: 만들지 않기 (선택하지 않으면 유지돼요)',
    'party_thread_choice_create':'만들기',
    'party_thread_choice_skip':'만들지 않기',
    'party_end_desc':'진행 중인 파티 모집을 즉시 종료할 수 있어요.',
    'party_end_option_name':'모집',
    'party_end_option_desc':'종료할 모집을 선택해 주세요.',
    'party_edit_desc':'진행 중인 내 파티 모집을 수정해요.',
    'party_edit_option_name':'모집',
    'party_edit_option_desc':'수정할 모집을 선택해 주세요.',
    'party_edit_success':'\'{title}\' 모집을 수정했어요.',
    'party_edit_failed':'모집을 수정하지 못했어요.',
    'party_slots_below_participants':'현재 {current}명이 참여 중이라 인원수를 그보다 적게 설정할 수 없어요.',
    'party_embed_desc_active':'{current}/{max_slots}명이 참여중이에요.',
    'party_embed_desc_ended':'종료된 모집이에요. {current}/{max_slots}명이 참여했어요.',
    'party_field_participants':'참여자 목록',
    'party_participant_line':'{index}. <@{member_id}>{suffix}',
    'party_host_suffix':' (방장)',
    'party_participant_empty':'(아직 참여자가 없어요.)',
    'party_btn_join':'참여하기',
    'party_btn_leave':'취소하기',
    'party_duration_part_hour':'{hours}시간',
    'party_duration_part_minute':'{minutes}분',
    'party_thread_name_fallback':'모집-{recruit_id}',
    'party_channel_invalid':'텍스트 채널이나 스레드에서만 모집을 시작할 수 있어요.',
    'party_invalid_duration':'시간 형식이 올바르지 않아요. 예: 2시간 30분, 45분',
    'party_invalid_slots':'인원수는 {min_slots}~{max_slots} 사이의 정수여야 해요.',
    'party_thread_channel_not_set':'비공개 스레드를 만들기 위해선 관리자가 `/설정`에서 파티 모집방을 먼저 지정해야 해요. 해당 서버의 소유자나 관리자에게 문의해주세요.',
    'party_start_success':'\'{title}\' 모집을 시작했어요.',
    'party_start_failed':'모집을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.',
    'party_not_found':'모집 정보를 찾을 수 없어요.',
    'party_already_ended':'이미 종료된 모집이에요.',
    'party_already_joined':'이미 참여 중이에요.',
    'party_not_joined':'참여 중이 아니에요.',
    'party_full':'모집 인원이 가득 찼어요.',
    'party_host_cannot_leave':'방장은 취소하기로 빠질 수 없어요. `/파티 모집종료`를 사용해 주세요.',
    'party_join_success':'참여자 목록에 추가했어요.',
    'party_leave_success':'참여자 목록에서 제거했어요.',
    'party_end_success':'\'{title}\' 모집을 종료했어요. ({current}/{max_slots}명)',
    'party_end_failed':'모집을 종료하지 못했어요.',
    'party_thread_open':'\'{title}\' 모집이 종료되어 비공개 스레드를 열었어요.\n방장: <@{host_id}>\n참여: {count}/{max_slots}명',
    'party_premium_denied':'이 서버에서는 사용할 수 없는 프리미엄 기능이에요.',

    ##### 초기설정 (onboarding) #####
    # 위치: Cogs/c_onboarding.py
    # onboarding 관련 문구는 default.py(기본 언어팩)에만 추가하세요. 애드온 tone에는 넣지 마세요.

    # /초기설정 슬래시 명령어
    'onboarding_command_desc':'유나봇의 초기 필수 설정을 진행할 수 있어요. (서버 소유자 전용)',

    # 서버 추가 시 DM/스레드 안내
    # 변수: {customer_name}
    'onboarding_greeting_default':'처음 뵙겠습니다, 치쿠마 유우나라고 해요! ',
    # 변수: {greeting}, {guild_name}
    'onboarding_join_message':'{greeting}**{guild_name}**에 유나봇이 추가되었어요.\n유나봇은 초기 설정이 필요해요. 먼저, 서버 소유자님께서 `/초기설정` 명령을 실행해 주세요.\n`/초기설정` 명령어는 기본 기능의 설정만 진행해요. 프리미엄 기능을 신청하신 경우 `/설정` 명령어에서 추가적인 설정을 부탁드려요.',

    # UI 공통
    'onboarding_view_expired':'초기 설정 메뉴가 만료되었어요. `/초기설정`을 다시 실행해 주세요.',
    'onboarding_thread_fallback_name':'봇 초기 설정 안내',
    'onboarding_owner_only':'서버 소유자만 사용할 수 있어요.',
    'onboarding_already_complete':'이미 초기 설정이 완료되었어요.',

    # 표시 형식
    'onboarding_fmt_unset':'(미설정)',
    'onboarding_fmt_owner_only':'서버 소유자만',
    'onboarding_fmt_all_members':'전체 멤버',
    'onboarding_fmt_enabled':'활성화',
    'onboarding_fmt_disabled':'비활성화',
    'onboarding_fmt_complete_status':'완료됨',

    # 채널 검증 (lib_channel_check에 전달)
    'onboarding_log_channel_unset':'로그 채널이 설정되지 않았어요.',
    'onboarding_log_channel_missing':'설정된 로그 채널을 찾을 수 없어요.',

    # 버튼
    'onboarding_btn_clear_admin_role':'관리자 역할 해제',
    'onboarding_btn_next':'다음',
    'onboarding_btn_back':'뒤로',
    'onboarding_btn_exp_enable':'경험치 켜기',
    'onboarding_btn_exp_disable':'경험치 끄기',
    'onboarding_btn_clear_exp_channel':'출석체크 채널 해제',
    'onboarding_btn_clear_exp_role':'기본 유저 역할 해제',
    'onboarding_btn_complete':'초기 설정 완료',

    # 셀렉트 placeholder
    'onboarding_placeholder_log_channel':'로그 채널을 선택해 주세요.',
    'onboarding_placeholder_admin_role':'봇의 설정을 관리할 수 있는 관리자의 역할을 선택해 주세요. (선택)',
    'onboarding_placeholder_exp_channel':'출석 메시지를 보낼 채널을 선택해 주세요. (선택)',
    'onboarding_placeholder_exp_role':'기본 유저 역할을 선택해 주세요. (선택)',

    # 알림(notice) 메시지
    'onboarding_notice_select_log_channel':'⚠ 로그 채널을 선택해 주세요.',
    # 변수: {channel}
    'onboarding_notice_log_channel_saved':'✅ 로그 채널을 {channel}(으)로 저장했어요.',
    'onboarding_notice_select_admin_role':'⚠ 관리자 역할을 선택해 주세요.',
    # 변수: {role}
    'onboarding_notice_admin_role_saved':'✅ 관리자 역할을 {role}(으)로 저장했어요.',
    'onboarding_notice_admin_role_cleared':'✅ 관리자 역할을 해제했어요. 이제 서버 소유자만 봇 관리자로 판단해요.',
    'onboarding_notice_log_channel_required':'⚠ 로그 채널을 먼저 선택해 주세요.',
    'onboarding_notice_general_done':'일반 설정은 이걸로 끝이에요! 경험치 기능을 사용할 지 설정해주세요.',
    'onboarding_notice_exp_enabled':'경험치 기능을 활성화했어요. 출석체크 메세지를 보낼 채널과 경험치 집계 대상이 되는 기본 유저 역할을 설정해 주세요.',
    'onboarding_notice_exp_disabled':'경험치 기능을 비활성화했어요. 아래 내용을 확인한 뒤 완료해 주세요.',
    # 변수: {channel}
    'onboarding_notice_exp_channel_saved':'✅ 출석 채널을 {channel}(으)로 저장했어요.',
    'onboarding_notice_exp_channel_cleared':'✅ 출석체크 채널을 해제했어요. 이제 출석체크 메세지를 보내지 않을게요.',
    # 변수: {role}
    'onboarding_notice_exp_role_saved':'✅ 기본 유저 역할을 {role}(으)로 저장했어요.',
    'onboarding_notice_exp_role_cleared':'✅ 기본 유저 역할을 해제했어요. 이제 모든 멤버를 대상으로 집계할게요.',
    'onboarding_notice_exp_detail_done':'경험치 상세 설정을 마쳤어요. 아래 내용을 확인한 뒤 완료해 주세요.',

    # 임베드
    'onboarding_embed_general_title':'초기 설정 — 1/4 일반',
    'onboarding_embed_general_desc':'로그 채널과 관리자 역할을 설정해 주세요.',
    'onboarding_embed_general_field_current':'현재 값',
    # 변수: {log_channel}, {admin_role}
    'onboarding_embed_general_field_value':'- 로그 채널: {log_channel}\n- 관리자 역할: {admin_role}',
    'onboarding_embed_general_footer':'로그 채널은 필수예요. 설정 후 `다음`을 눌러 주세요.',

    'onboarding_embed_exp_enable_title':'초기 설정 — 2/4 경험치 활성화',
    'onboarding_embed_exp_enable_desc':'경험치 기능을 사용할지 선택해 주세요.',
    # 변수: {status}
    'onboarding_embed_exp_enable_field_value':'- 경험치 기능: {status}',
    'onboarding_embed_exp_enable_footer':'끄기를 선택하면 상세 설정 없이 완료 단계로 이동해요.',

    'onboarding_embed_exp_detail_title':'초기 설정 — 3/4 경험치 상세',
    'onboarding_embed_exp_detail_desc':'출석체크 메세지를 보낼 채널(선택하지 않으면 보내지 않음)과 경험치 집계 대상이 되는 기본 유저 역할(선택하지 않으면 전체 유저를 대상으로 집계)을 설정해 주세요.',
    # 변수: {exp_channel}, {exp_role}
    'onboarding_embed_exp_detail_field_value':'- 출석 채널: {exp_channel}\n- 기본 유저 역할: {exp_role}',
    'onboarding_embed_exp_detail_footer':'두 항목 모두 선택 사항이에요. 설정 후 `다음`을 눌러 주세요.',

    'onboarding_embed_complete_title':'초기 설정 — 4/4 완료',
    'onboarding_embed_complete_desc':'아래 내용을 확인한 뒤 `초기 설정 완료`를 눌러 주세요.',
    'onboarding_embed_complete_field_general':'일반',
    # 변수: {log_channel}, {admin_role}
    'onboarding_embed_complete_field_general_value':'- 로그 채널: {log_channel}\n- 관리자 역할: {admin_role}',
    'onboarding_embed_complete_field_exp':'경험치',
    # 변수: {exp_lines}
    'onboarding_embed_complete_field_exp_value':'{exp_lines}',
    # 변수: {status}, {exp_channel}, {exp_role}
    'onboarding_embed_exp_lines_disabled':'- 기능: {status}',
    'onboarding_embed_exp_lines_enabled':'- 기능: {status}\n- 출석 채널: {exp_channel}\n- 기본 유저 역할: {exp_role}',
    'onboarding_embed_complete_field_status':'상태',

    # 완료 처리
    'onboarding_complete_missing_required':'아직 필수 설정이 빠져 있어요.\n- 로그 채널',
    # 변수: {issue}
    'onboarding_complete_log_channel_issue':'로그 채널을 사용할 수 없어요.\n{issue}',
    # 변수: {issue}
    'onboarding_complete_exp_channel_issue':'출석 채널을 사용할 수 없어요.\n{issue}',
    'onboarding_complete_sync_failed':'초기 설정은 저장됐지만 명령어 목록 갱신에 실패했어요. 잠시 후 다시 시도하거나 봇을 재시작해 주세요.',
    'onboarding_complete_success':'초기 설정을 완료했어요! 이제 `/정보`, `/경험치`, `/알림`, `/설정` 명령을 사용할 수 있어요.',

    ##### 서버 설정 (setting) #####
    # 위치: Cogs/c_setting.py
    # setting 관련 문구는 default.py(기본 언어팩)에만 추가하세요.
    # 애드온 설정 문구는 각 애드온 톤 파일에만 추가하세요.

    # /설정 슬래시 명령어
    'setting_command_desc':'서버의 봇 설정을 조회하거나 변경할 수 있어요. (관리자 전용)',
    'setting_option_category_name':'카테고리',
    'setting_option_category_desc':'어떤 설정을 조회·변경할지 선택해 주세요.',

    # 카테고리 이름 (자동완성·임베드 제목)
    'setting_category_basic':'기본',
    'setting_category_exp':'경험치',
    'setting_category_verify':'인증방',
    'setting_category_party':'파티',
    'setting_category_addon':'애드온',

    # UI 공통
    'setting_view_expired':'설정 메뉴가 만료되었어요. `/설정`을 다시 실행해 주세요.',
    'setting_select_item_placeholder':'변경할 항목을 선택해 주세요.',
    'setting_btn_back_to_list':'목록으로',
    'setting_btn_refresh':'새로고침',
    'setting_btn_clear':'해제',
    'setting_btn_change':'변경',
    'setting_btn_enable':'켜기',
    'setting_btn_disable':'끄기',
    'setting_refresh_done':'설정을 다시 불러왔어요.',
    'setting_channel_placeholder':'채널을 선택해 주세요.',
    'setting_role_placeholder':'역할을 선택해 주세요.',
    'setting_profile_placeholder':'언어팩을 선택해 주세요.',
    'setting_change_ui_not_ready':'이 항목은 아직 변경 UI가 준비되지 않았어요.',
    'setting_perm_denied':'이 명령어는 서버 관리자 또는 봇 관리 역할이 있어야 사용할 수 있어요.',
    'setting_category_unknown':'알 수 없는 카테고리에요.',
    'setting_category_unavailable':'이 카테고리는 이 서버에서 사용할 수 없어요.',

    # 임베드 색상 모달
    'setting_embed_color_modal_title':'임베드 색상 변경',
    'setting_embed_color_input_label':'해시코드',
    'setting_embed_color_input_placeholder':'원하시는 색상의 해시코드를 c0ffee 또는 #c0ffee처럼 입력해주세요.',

    # 텍스트 설정 모달
    'setting_text_modal_label':'내용',
    'setting_text_modal_placeholder':'원하는 내용을 입력해 주세요.',
    # 변수: {label}
    'setting_text_modal_title':'{label} 변경',

    # 인증 질문 편집 UI
    'setting_verify_questions_notice':'아래 목록에서 질문을 선택해 주세요.',
    'setting_verify_select_question_placeholder':'수정할 질문을 선택해 주세요.',
    'setting_verify_btn_add':'질문 추가',
    'setting_verify_btn_back':'뒤로',
    'setting_verify_btn_edit':'질문 수정',
    'setting_verify_btn_move':'순서 변경',
    'setting_verify_btn_delete':'질문 삭제',
    'setting_verify_max_questions':'질문은 최대 4개까지 등록할 수 있어요.',
    # 변수: {index}
    'setting_verify_question_selected':'{index}번 질문을 선택했어요.',
    'setting_verify_question_not_found':'선택한 질문을 찾을 수 없어요.',
    'setting_verify_modal_add_title':'질문 추가',
    # 변수: {index}
    'setting_verify_modal_edit_title':'{index}번 질문 수정',
    'setting_verify_modal_index_label':'질문 번호 (1~4)',
    'setting_verify_modal_index_placeholder':'추가할 위치(기존 질문은 뒤로 밀려요)',
    'setting_verify_modal_question_label':'질문',
    'setting_verify_modal_question_placeholder':'질문을 입력해주세요.',
    'setting_verify_modal_answers_label':'정답 (선택)',
    'setting_verify_modal_answers_placeholder':'한 줄에 하나씩 입력해주세요. 비우면 정답이 없는 서술형 질문이 돼요.',
    # 변수: {index}
    'setting_verify_modal_move_title':'{index}번 질문 순서 변경',
    'setting_verify_modal_move_label':'새 번호 (1~4)',
    'setting_verify_modal_move_placeholder':'이동할 번호를 입력해 주세요.',

    # 임베드
    # 변수: {category}
    'setting_embed_status_title':'서버 설정 현황 — {category}',
    'setting_embed_item_title':'설정 항목',
    'setting_embed_item_unavailable':'이 항목은 이 서버에서 사용할 수 없어요.',
    # 변수: {label}
    'setting_embed_item_detail_title':'설정 항목: {label}',
    'setting_embed_current_value':'현재 값',
    'setting_embed_verify_howto':'아래 목록에서 질문을 선택해 주세요. 새 질문은 `질문 추가` 버튼을 사용해 주세요.',
    # 변수: {clear_label}
    'setting_embed_color_howto_clearable':'`변경` 버튼을 누르면 모달이 열려요. 원하시는 색상을 헥스코드 6자리로 입력해 주세요. `{clear_label}` 버튼을 누르면 기본값으로 바꿀 수 있어요.',
    'setting_embed_color_howto':'`변경` 버튼을 누르면 모달이 열려요. 원하시는 색상을 헥스코드 6자리로 입력해 주세요.',
    'setting_embed_change_method':'변경 방법',
    'setting_embed_footer':'아래 목록에서 변경할 설정을 선택해 주세요.',
    'setting_exp_warning_field':'출석 알림 기능 관련 안내',

    # 표시 형식
    'setting_fmt_bool_on':'켜짐',
    'setting_fmt_bool_off':'꺼짐',
    'setting_fmt_role_unset':'(미설정 — 서버 소유자만)',
    # 변수: {role_id}
    'setting_fmt_role_deleted':'(삭제된 역할 ID {role_id})',
    'setting_fmt_channel_unset':'(미설정)',
    'setting_fmt_exp_role_all':'(미설정 — 모든 멤버를 집계하는 중)',
    'setting_log_channel_missing':'설정된 로그 채널을 찾을 수 없어요. 채널이 삭제된 것 같아요.',
    'setting_verify_questions_unset':'(미설정)',
    'setting_verify_answer_descriptive':'서술형',
    # 변수: {count}
    'setting_verify_answer_count':'정답 {count}개',
    'setting_unknown_value':'(알 수 없음)',
    'setting_not_clearable':'이 설정은 해제할 수 없어요.',
    # 변수: {issue}
    'setting_channel_permission_hint':'{issue}\n다른 텍스트 채널을 선택하거나, 봇에게 해당 채널의 보기·메시지 전송 권한을 부여해 주세요.',
    'setting_role_not_found':'선택한 역할을 찾을 수 없어요.',
    # 변수: {detail}
    'setting_save_error':'설정을 저장하는 중 오류가 발생했어요: {detail}',
    'setting_saved_generic':'설정을 저장했어요.',
    'setting_feature_enable_block':'로그 채널이 설정되지 않았어요. 일반 설정에서 로그 채널을 먼저 지정해 주세요.',
    # 변수: {issue}
    'setting_feature_enable_block_log_issue':'로그 채널을 사용할 수 없어요.\n{issue}',

    # 설정 항목 — 기본·경험치·인증·파티 (애드온 항목은 addon tone에 정의)
    'setting_spec_exp_enable_label':'경험치 기능 활성화 여부',
    'setting_spec_exp_enable_desc':'경험치 기능을 켜거나 끌 수 있어요.',
    'setting_spec_exp_channel_label':'출석체크 알림 채널 설정',
    'setting_spec_exp_channel_desc':'출석체크 알림을 보낼 채널을 바꿀 수 있어요.',
    'setting_spec_exp_channel_clear':'보내지 않기',
    'setting_spec_exp_role_label':'경험치 집계 대상 역할',
    'setting_spec_exp_role_desc':'지정한 역할을 가진 멤버만 경험치를 집계할 수 있어요.',
    'setting_spec_exp_role_clear':'역할 제한 해제',
    'setting_spec_bot_admin_role_label':'봇 관리자 역할',
    'setting_spec_bot_admin_role_desc':'봇 설정을 변경할 수 있는 관리자 역할을 지정할 수 있어요.',
    'setting_spec_bot_admin_role_clear':'지정 해제',
    'setting_spec_bot_log_channel_label':'로그 채널',
    'setting_spec_bot_log_channel_desc':'오류·실패·투명성 보고 등의 알림을 보낼 채널을 지정할 수 있어요.',
    'setting_spec_embed_color_label':'임베드 색상',
    'setting_spec_embed_color_desc':'헥스코드(예: a57bdb 또는 #a57bdb)를 입력해 바꿀 수 있어요.',
    'setting_spec_embed_color_clear':'기본값으로 복원',
    'setting_spec_tone_profile_label':'언어팩',
    'setting_spec_tone_profile_desc':'서버에서 사용할 언어팩을 변경할 수 있어요.',
    'setting_spec_verify_enable_label':'가입신청 활성화 여부',
    'setting_spec_verify_enable_desc':'신규 유저 대상 가입신청 기능을 켜거나 끌 수 있어요.',
    'setting_spec_verify_questions_label':'가입 신청 질문',
    'setting_spec_verify_questions_desc':'최대 4개의 질문과 정답을 관리할 수 있어요.',
    'setting_spec_verify_panel_channel_label':'가입 신청 패널 채널',
    'setting_spec_verify_panel_channel_desc':'가입 신청 버튼이 게시될 채널을 지정할 수 있어요.',
    'setting_spec_verify_log_channel_label':'가입 신청서 검토 로그 채널',
    'setting_spec_verify_log_channel_desc':'가입 신청서와 승인/거절 버튼을 보낼 채널을 지정할 수 있어요.',
    'setting_spec_verify_role_label':'승인 시 부여할 역할',
    'setting_spec_verify_role_desc':'가입 승인 시 부여할 역할을 지정할 수 있어요.',
    'setting_spec_verify_repass_enable_label':'기존 인증 유저 프리패스 여부',
    'setting_spec_verify_repass_enable_desc':'이전에 인증을 완료한 유저가 다시 가입할 때 가입 신청 없이 즉시 통과할지 설정할 수 있어요.',
    'setting_spec_verify_auto_reject_wrong_label':'오답 자동 거절 여부',
    'setting_spec_verify_auto_reject_wrong_desc':'정답이 설정된 질문에서 오답이면 관리자 검토 없이 자동 거절할지 설정할 수 있어요. 추방은 하지 않고 틀렸다고만 표시해요.',
    'setting_spec_recruit_thread_channel_label':'파티 모집방',
    'setting_spec_recruit_thread_channel_desc':'파티 모집 종료 시 비공개 스레드를 만들 채널이에요. 참여자가 스레드에서 대화하려면 원하는 역할에 채널 보기·메시지 기록 보기·스레드에서 메시지 보내기 권한이 필요해요.',
    'setting_spec_recruit_thread_channel_clear':'지정 해제',

    # 설정 저장 완료 메시지 — 기본·경험치·인증·파티
    'setting_saved_exp_enable_on':'지금부터 경험치를 집계할게요.',
    'setting_saved_exp_enable_off':'지금부터 경험치를 집계하지 않을게요.',
    'setting_saved_exp_channel_off':'이제 출석체크 알림을 보내지 않을게요.',
    # 변수: {channel_id}
    'setting_saved_exp_channel_on':'이제 출석체크 알림을 <#{channel_id}>에 보낼게요.',
    'setting_saved_exp_role_off':'이제 모든 멤버의 경험치를 집계할게요.',
    # 변수: {role_id}
    'setting_saved_exp_role_on':'이제 <@&{role_id}> 역할이 있는 멤버만 경험치를 집계할게요.',
    'setting_saved_bot_admin_role_off':'봇 관리자 역할 지정을 해제했어요. 앞으로는 서버 소유자만 봇 관리자로 판단할게요.',
    # 변수: {role_id}
    'setting_saved_bot_admin_role_on':'봇 관리자 역할을 <@&{role_id}>으로 설정했어요.',
    # 변수: {channel_id}
    'setting_saved_bot_log_channel':'로그 채널을 <#{channel_id}>으로 설정했어요.',
    # 변수: {color}
    'setting_saved_embed_color':'임베드 색상을 `{color}`으로 설정했어요.',
    # 변수: {profile_title}
    'setting_saved_tone_profile':'언어팩을 `{profile_title}`(으)로 변경했어요.',
    'setting_saved_verify_enable_on':'가입 신청 기능을 활성화했어요.',
    'setting_saved_verify_enable_off':'가입 신청 기능을 비활성화했어요.',
    # 변수: {channel_id}
    'setting_saved_verify_panel_channel':'가입 신청 버튼을 게시할 채널을 <#{channel_id}>으로 설정했어요.',
    # 변수: {channel_id}
    'setting_saved_verify_log_channel':'가입 신청서를 검토할 로그 채널을 <#{channel_id}>으로 설정했어요.',
    # 변수: {role_id}
    'setting_saved_verify_role':'가입 승인시 부여할 역할을 <@&{role_id}>으로 설정했어요.',
    'setting_saved_verify_repass_enable_on':'이제 기존에 승인받은 유저는 또 다시 승인을 받지 않아도 통과시킬게요.',
    'setting_saved_verify_repass_enable_off':'이제 기존에 승인받은 유저도 또 다시 승인을 받게 할게요.',
    'setting_saved_verify_auto_reject_wrong_on':'이제 오답은 자동으로 거절할게요.',
    'setting_saved_verify_auto_reject_wrong_off':'이제 오답도 자동으로 거절하지 않을게요.',
    'setting_saved_verify_questions':'질문을 저장했어요.',
    'setting_saved_recruit_thread_channel_off':'파티 모집방 지정을 해제했어요.',
    'setting_saved_recruit_thread_channel_on':'파티 모집방을 <#{channel_id}>으로 설정했어요.',

    # 인증 질문 저장/검증 메시지
    'setting_verify_index_invalid':'질문 번호는 1~4 사이의 숫자로 입력해 주세요.',
    'setting_verify_index_out_of_range':'질문 번호는 1~4 사이여야 해요.',
    'setting_verify_index_not_number':'질문 번호는 숫자로 입력해 주세요.',
    'setting_verify_question_not_exists':'해당 번호의 질문이 없어요.',
    # 변수: {index}
    'setting_verify_question_saved':'{index}번 질문을 저장했어요.',
    'setting_verify_question_max':'질문은 최대 4개까지 등록할 수 있어요.',
    # 변수: {max_index}
    'setting_verify_question_insert_range':'질문 번호는 1~{max_index} 사이로 입력해 주세요.',
    # 변수: {index}
    'setting_verify_question_inserted':'{index}번에 질문을 추가했어요. 기존 질문은 뒤로 밀렸어요.',
    # 변수: {index}
    'setting_verify_question_deleted':'{index}번 질문을 삭제했어요.',
    'setting_verify_move_source_missing':'기존 번호의 질문이 없어요.',
    'setting_verify_move_target_invalid':'새 번호는 1~4 사이여야 해요.',
    # 변수: {source}, {target}
    'setting_verify_question_moved':'{source}번 질문을 {target}번으로 이동했어요.',

}
