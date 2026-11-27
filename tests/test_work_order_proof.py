from chillwatch.maintenance_slots import reconcile_schedule


def slot(unit,**changes):
    return {'state':'已排检','unit':unit,'crew':1,'start':605,'end':630,'allowed_start':600,
            'allowed_end':660,'runtime':25,'has_backup':True,'rack':'A'}|changes


def test_adjacent_same_rack_work_schedule_does_not_overlap():
    one=slot('F1')
    two=slot('F2',start=630,end=655)
    result=reconcile_schedule([one,two])
    assert result['verified']
    assert result['crew_minutes']=={'1':50}
    assert result['total_crew_minutes']==50


def test_overlap_counts_rack_even_when_two_crews_are_available():
    a=slot('F1')
    b=slot('F2',crew=2,start=610,end=635)
    result=reconcile_schedule([a,b])
    assert result['defects']==[{'reason':'RACK_REDUNDANCY_BROKEN','identity':'A','units':['F1','F2'],'overlap':[610,630]}]
    assert not result['verified']


def test_wrong_duration_and_without_backup_are_both_retained():
    result=reconcile_schedule([slot('F1',end=631,has_backup=False)])
    assert [row['reason'] for row in result['defects']]==['OUTSIDE_APPROVED_WINDOW','MISSING_STANDBY_MACHINE']


def test_non_scheduled_row_may_not_reserve_crew():
    result=reconcile_schedule([slot('F1',state='候补')])
    assert result['scheduled']==0
    assert result['defects']==[{'unit':'F1','reason':'UNPAID_SLOT_PRESENT'}]


def test_payload_with_malformed_span_reports_instead_of_overlapping():
    result=reconcile_schedule([slot('F1',end=None)])
    assert result['total_crew_minutes']==0
    assert result['defects']==[{'unit':'F1','reason':'MALFORMED_WORK_SLOT'}]
