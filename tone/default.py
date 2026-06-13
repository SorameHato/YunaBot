# coding: utf-8

# 언어팩 정보
PARM_TYPE = 0 # 0:통상 1:P계약자용(단일서버) 2:P계약자용(복수서버) 3:수주계약자용
PARM_TITLE = '기본 언어팩'
PARM_DESC = '(※ 아직 하늘봇 대사 그대로입니다, 6월 말까지 수정 예정) 유나봇의 기본 언어팩입니다. 모두에게 사근사근하면서 어딘가 나긋한 성격인 치쿠마 유나를 최대한 구현…할 수 있었으면 하토가 소설을 몇 번씩 탈고했는데도 만족을 못 해서 결국엔 버리지 않았겠죠? (실제로 Dream Collector 0~3화는 2018년 6월부터 지금(2026년 5월)까지 14번째 탈고 중)'


# 변수는 {변수명} 으로 사용하실 수 있습니다.
# 앞에 (필수)라고 붙은 변수가 아닌 이상, 전부 선택입니다.
# 아래의 언어팩은 '항목 이름':'대사' 형식으로 이루어져 있습니다. 항목 이름은 절대로 바뀌면 안 됩니다. 대사는 : 뒤쪽에 입력해 주세요. 또한, 각 항목 뒤엔 쉼표(,)가 있어야 합니다.

# 언어팩 내용
LANG_PACK = {
    ##### 활동 경험치 #####

    #### A. 출석체크 콜백 ####
    # 출석체크는 하루 한 번, 첫 번째 채팅을 전송하면 자동으로 완료됩니다. 출석체크가 완료되었을 때 지정한 채널로 전송할 채팅입니다. (전송을 하지 않게 설정할 수도 있습니다.)
    # 변수
    # * {author} : 유저 표시 이름 (username) — 예: 하토 (hanamuke_no_hanataba)
    # * {d_arg} : 해당 유저가 며칠만에 다시 찾아왔는지 (예를 들어 하루만에 찾아왔으면 1, 3일만에 찾아왔으면 3)
    # 위치 : c_expFE > on_message

    # 출석체크 중 오류가 발생했을 때 전송될 채팅
    'expFE_res_error_title':'{author}님, 환영합니다.',
    'expFE_res_error_desc':'출석 체크 중에 오류가 발생했어요. 아마 출석 체크 자체는 되었을 것 같지만, 이 메세지가 계속 나온다면 하토를 불러주세요.',

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

    #### B. 경험치 슬래시 명령어 ####
    # 설정에 표시되는 설명입니다.
    'expFE_group_name':'활동 경험치 기능 관련 명령어에요. (현황, 랭킹 등)',

    #### C. 경험치 현황 ####
    # /경험치 현황 명령어의 설명입니다.
    'expFE_status_desc':'경험치 현황을 볼 수 있어요.',

    # /경험치 현황 명령어를 입력했을 때, 해당 명령어의 답장으로 전송될 채팅(embed)입니다. 제목과 필드 4개(등록일자, 출석일수, 통화 시간, 채팅 개수)로 이루어져 있습니다.
    # 변수
    # * {author} : 유저 표시 이름 (username) — 예: 하토 (hanamuke_no_hanataba)
    # * (필수) {exp} : 해당 유저의 경험치
    # * {exp_incr} : 해당 유저의 경험치 증가분
    'expFE_status_embed_title':'{author} 님의 활동 경험치는 {exp} (▲ {exp_incr})(이)에요.',
    'expFE_status_embed_field1':'유나봇과 함께 하기 시작한 날',
    'expFE_status_embed_field2':'유나봇과 함께한 나날 (출석 일수)',
    'expFE_status_embed_field3':'통화 시간',
    'expFE_status_embed_field4':'채팅 갯수',

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

    # '통화 시간'은 시간에 따라 아래의 값들이 합쳐져서 표시됨
    'expFE_voice_duration_zero':'0초', #시간이 없는 경우
    'expFE_voice_unit_hour':'{value}시간', #1시간 (60분 미만인 경우 표시 X)
    'expFE_voice_unit_minute':'{value}분', #2분 (60초 미만인 경우 표시 X)
    'expFE_voice_unit_second':'{value}초', #3초 (소숫점 없는 경우 - 정확히 n.0초인 경우)
    'expFE_voice_unit_second_frac':'{value}초', #3.4초 #소숫점 있는 경우

    #### D. 경험치 랭킹(채팅) ####
    # /경험치 랭킹 명령어의 설명과 옵션입니다.
    'expFE_ranking_desc':'경험치 랭킹을 볼 수 있어요.',
    'expFE_ranking_option1_name':'종류',
    'expFE_ranking_option1_desc':'누적 순위를 표시할 지, 아니면 오늘/어제 얻은 경험치 순위를 표시할 지 선택해 주세요.',
    'expFE_ranking_option1_choice0':'누적 순위',
    'expFE_ranking_option1_choice1':'오늘 순위',
    'expFE_ranking_option1_choice2':'어제 순위',
    'expFE_ranking_option2_name':'페이지',
    'expFE_ranking_option2_desc':'몇 페이지를 표시할지 입력해주세요. (한 페이지에 20명)',
    'expFE_ranking_option3_name':'스타일',
    'expFE_ranking_option3_desc':'출력 스타일을 선택해주세요.',
    'expFE_ranking_option3_choice0':'모던',
    'expFE_ranking_option3_choice1':'텍스트',
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


    #### D-1. 경험치 랭킹 (추후 ameame3 구현에서 사용) ####
    # 변수 : token=ameame3 SDK에서 받은 토큰, usr=내부망 ID (SorameHato@AmenyanDaisuki1031!)
    'expFE_ranking_callback_ts':'▶ https://ameneko.taile2a0c8.ts.net/l/ameame2_bridge/ameame3/v8/{token}/{usr}',
    'expFE_ranking_callback_outer':'▶ https://amene.co?{token2}={usr}',

    #### E. 경험치 멘션 ####
    # /경험치 멘션 명령어를 입력했을 때, 해당 명령어의 답장으로 전송될 채팅입니다.
    # 변수 : {result} : changeSilentStatus의 반환값

    # 해당 명령어의 설명
    'expFE_mention_desc':'출석 체크 시의 멘션을 켜고 끌 수 있어요.',
    'expFE_mention_option_name':'멘션',
    'expFE_mention_option_desc':'출석 체크 시 멘션을 켤지 끌지 선택해주세요.',
    'expFE_mention_option_choice_on':'켜기',
    'expFE_mention_option_choice_off':'끄기',

    # 성공적으로 켜고 껐을 때
    'expFE_mention_on':'성공적으로 멘션을 켰어요!',
    'expFE_mention_off':'성공적으로 멘션을 껐어요!',

    # 오류가 발생했을 때
    'expFE_mention_error_bool':'오류가 발생했어요! (arg == 부울(bool)형 Method인 경우)',
    'expFE_mention_error_none':'오류가 발생했어요! (arg == None인 경우)',
    'expFE_mention_error_undef':'오류가 발생했어요! (알 수 없는 오류, result : {result})',

    ##### 일일알림 #####

    #### A. 알림 슬래시 명령어 ####
    # 설정에 표시되는 설명입니다.
    'dailyInform_group_desc':'매일 정해진 시간에 전송할 알림을 관리하는 명령어에요.',

    #### B. 등록 ####
    # 알림을 등록하는 기능이에요.
    # 변수
    # * {time} : 보낼 시간
    # * {message} : 보낼 메세지

    # /알림 등록 명령어의 설명과 옵션
    'dailyInform_add_desc':'매일 전송할 알림을 등록할 수 있어요.',
    'dailyInform_add_option1_name':'시간',
    'dailyInform_add_option1_desc':'알림을 보낼 시간을 HHMM 형식으로 입력해주세요. 예: 1031, 1750',
    'dailyInform_add_option_message_name':'메세지',
    'dailyInform_add_option_message_desc':'전송할 메세지를 입력해주세요.',

    # 응답
    # 메세지가 없는 경우
    'dailyInform_add_empty_message':'등록할 메세지를 입력해주세요.',
    # 메세지 등록에 성공한 경우
    'dailyInform_add_success':'매일 {time}에 \'{message}\' 라고 전송할게요.',

    #### C. 조회 ####
    # 등록된 알림을 조회하는 기능이에요.

    # /알림 조회 명령어의 설명과 옵션
    'dailyInform_list_desc':'등록된 알림을 조회할 수 있어요.',
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
    'dailyInform_list_empty':'이 서버에는 등록된 알림이 없어요.',
    # 해당 페이지엔 출력할 알림이 없는 경우
    'dailyInform_list_page_empty':'{page}페이지엔 출력할 알림이 없어요.',
    # 결과가 있는 경우
    'dailyInform_list_header':'총 {total}개 중 {start}~{end}번째에요.',
    # 각 줄의 형식
    # * {authors} : 등록자(및 관리자 편집 시 편집자) 멘션 (<@id>)
    'dailyInform_list_line':'{order}. {message} ({time}, ID : {id}, {authors})',
    'dailyInform_list_authors_only':'등록자 : {author}',
    'dailyInform_list_authors_with_editor':'등록자 : {author}, 편집자 : {editor}',

    #### D. 시간/메세지 변경 ####
    # /알림 시간변경/내용수정 명령어의 설명과 옵션
    'dailyInform_edit_desc_time':'등록된 알림의 시간을 변경할 수 있어요.',
    'dailyInform_edit_desc_msg':'등록된 알림의 내용을 수정할 수 있어요.',
    'dailyInform_edit_option1_name':'id',
    'dailyInform_edit_option1_desc':'수정할 알림의 ID를 입력해주세요.',
    'dailyInform_edit_option2_time_name':'시간',
    'dailyInform_edit_option2_time_desc':'변경할 시간을 HHMM 형식으로 입력해주세요. 예: 1031, 1750',
    'dailyInform_edit_option2_msg_name':'메세지',
    'dailyInform_edit_option2_msg_desc':'변경할 메세지를 입력해주세요.',

    # 응답
    # 변수
    # * {message} : 기존 메세지
    # * {time} : 기존 시간
    # * {new_message} : 변경할 메세지
    # * {new_time} : 변경할 시간
    'dailyInform_edit_time_confirm':'앞으로 \'{message}\'를 {time}이 아닌 {new_time}에 보낼까요?',
    'dailyInform_edit_time_success':'이제 \'{message}\'를 {new_time}에 보낼게요.',
    'dailyInform_edit_msg_empty':'메세지가 입력되지 않았어요.',
    'dailyInform_edit_msg_confirm':'앞으로 {time}에 \'{message}\' 대신 \'{new_message}\' 라고 보낼까요?',
    'dailyInform_edit_msg_success':'이제 {time}에 \'{new_message}\' 라고 보낼게요.',

    #### E. 메세지 삭제 ####
    # /알림 삭제 명령어의 설명과 응답
    'dailyInform_delete_desc':'등록된 알림을 삭제할 수 있어요.',
    'dailyInform_delete_option1_name':'id',
    'dailyInform_delete_option1_desc':'삭제할 알림의 ID를 입력해주세요.',

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
    'dailyInform_btn_cancel':'취소',

    # 취소 버튼을 누른 경우
    'dailyInform_confirm_cancelled':'취소했어요.',
    # 이미 삭제된 경우
    'dailyInform_confirm_already_deleted':'이미 삭제된 알림이에요.',
    # 이미 해당 시간에 등록된 메세지가 있는 경우
    # {time} : 시간
    'dailyInform_add_duplicate':'이미 {time}엔 등록된 메세지가 있어요.',
    # DM인 경우
    'dailyInform_guild_only':'서버에서만 사용할 수 있는 명령어에요.',
    # 시간이 올바르지 않은 경우
    'dailyInform_invalid_time':'시간은 0000부터 2359까지의 HHMM 형식으로 입력해주세요. 예: 1031, 1730',
    # ID가 잘못된 경우
    'dailyInform_not_found':'해당 ID의 알림을 찾을 수 없어요.',
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
    'dailyInform_guild_unknown':'ID {guild_id}',

    ##### 정보 #####
    # 봇 이름 (render_default_name)
    'bot_name':'유나봇',
    # {bot_name} : 봇 이름
    # /정보 명령어 설명
    'info_command_desc':'봇 정보를 확인할 수 있어요.',
    # 응답
    'info_response_title':'{bot_name}의 정보에요.',
    'info_response_desc':'> 버전 : {ver} (APPEND : {addon})\n> 개발자 : 소라메 하토 (SorameHato@protonmail.ch)\n> 이 봇은 설레봇 v3.2.61 build 258(2023-06-04)과 하늘봇 v3.12.2-ame.8 rev 201 (2024-10-19 15:18)을 기반으로 한 박하맛 사탕(AmeBot)/네코마타 아쿠마(KumaBot) 개발중단 당시 최종버전의 FE/BE, LiveKiosk v7.0.0-ame.47의 DB API를 기반으로 만들어졌어요.',

    # 오류가 발생한 경우
    'error_title':'아무래도 바보토끼가 또 바보토끼 한 것 같아요. 하토를 불러주세요!',
    'error_embed_title':'자세한 내용',
    'error_embed_field1':'보낸 분',
    'error_embed_field2':'보낸 명령어',
    'error_embed_footer':'유나봇 버전 {ver}',
    'error_embed_photo':'https://amene.co/lapis10.png',

}