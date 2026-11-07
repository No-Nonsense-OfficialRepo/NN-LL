from lantool.qt.quickstart import QuickStart


def test_next_and_back_advance_exactly_one_host_step():
    practice = QuickStart()
    practice.choose('host')
    assert practice.state['tutorialStage'] == 'hostOpen'
    practice.nextLesson()
    assert practice.state['tutorialStage'] == 'hostInvite'
    practice.backLesson()
    assert practice.state['tutorialStage'] == 'hostOpen'
    practice.backLesson()
    assert practice.state['tutorialStage'] == 'choose'


def test_next_and_back_restore_client_state():
    practice = QuickStart()
    practice.choose('client')
    practice.nextLesson()
    assert practice.state['tutorialStage'] == 'clientKey'
    practice.nextLesson()
    assert practice.state['tutorialStage'] == 'clientPassword'
    assert practice.state['roomPasswordPrompt']
    practice.backLesson()
    assert practice.state['tutorialStage'] == 'clientKey'
    assert practice.state['roomPasswordPrompt'] is None
    practice.nextLesson()
    practice.nextLesson()
    assert practice.state['tutorialStage'] == 'clientInstall'
    practice.backLesson()
    assert practice.state['tutorialStage'] == 'clientPassword'
