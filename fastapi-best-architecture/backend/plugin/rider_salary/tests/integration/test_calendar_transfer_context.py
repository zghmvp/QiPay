"""P2-08：换站后查看历史月份，空白日仍用换站前站点的日标记、导入覆盖和周期。"""

from datetime import date, timedelta

from factories import (
    create_rider,
    create_site,
    expect_ok,
    generate_month,
    get_period,
    import_completed_orders,
    order_row,
)
from runtime import ApiClient


def _dates(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    days: list[str] = []
    while cursor <= last:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _put_flags(
    client: ApiClient,
    headers: dict[str, str],
    *,
    site_id: int,
    days: list[str],
    remark: str,
    bad_weather: bool = False,
    high_temp: bool = False,
) -> None:
    expect_ok(
        client.put(
            '/rider-salary/day-flags',
            headers=headers,
            json={
                'site_id': site_id,
                'days': [
                    {
                        'biz_date': day,
                        'bad_weather': bad_weather,
                        'high_temp': high_temp,
                        'remark': remark,
                    }
                    for day in days
                ],
            },
        )
    )


def test_september_calendar_keeps_old_site_before_transfer(
    client: ApiClient,
    admin_token: dict[str, str],
) -> None:
    """骑手 9/15 从甲站换到乙站后，9 月 1–14 日使用甲站的日标记和周期。"""
    site_a = create_site(client, admin_token, name='换站甲站')
    site_b = create_site(client, admin_token, name='换站乙站')
    rider = create_rider(
        client,
        admin_token,
        site_id=site_a['id'],
        name='换站骑手',
        hire_date='2026-09-01',
    )
    import_completed_orders(
        client,
        admin_token,
        site_id=site_a['id'],
        site_code=site_a['code'],
        job_no=rider['job_no'],
        rows=[
            order_row(f'{rider["job_no"]}-0901', '2026-09-01'),
            order_row(f'{rider["job_no"]}-0914', '2026-09-14'),
        ],
    )
    expect_ok(
        client.put(
            f'/rider-salary/riders/{rider["id"]}',
            headers=admin_token,
            json={'site_id': site_b['id'], 'reason': '换到乙站'},
        )
    )
    import_completed_orders(
        client,
        admin_token,
        site_id=site_b['id'],
        site_code=site_b['code'],
        job_no=rider['job_no'],
        rows=[
            order_row(f'{rider["job_no"]}-0915', '2026-09-15'),
            order_row(f'{rider["job_no"]}-0930', '2026-09-30'),
        ],
    )
    _put_flags(
        client,
        admin_token,
        site_id=site_a['id'],
        days=_dates('2026-09-01', '2026-09-14'),
        remark='甲站历史',
        bad_weather=True,
    )
    _put_flags(
        client,
        admin_token,
        site_id=site_b['id'],
        days=_dates('2026-09-01', '2026-09-30'),
        remark='乙站当前',
        high_temp=True,
    )
    period_a = get_period(
        client,
        admin_token,
        generate_month(client, admin_token, site_id=site_a['id'], month='2026-09')['id'],
    )
    period_b = get_period(
        client,
        admin_token,
        generate_month(client, admin_token, site_id=site_b['id'], month='2026-09')['id'],
    )
    current = expect_ok(client.get(f'/rider-salary/riders/{rider["id"]}', headers=admin_token))
    assert current['site_id'] == site_b['id']

    month = expect_ok(
        client.get(
            f'/rider-salary/calendar/{rider["id"]}',
            headers=admin_token,
            params={'month': '2026-09'},
        )
    )
    by_day = {item['date']: item for item in month['days']}
    for day in _dates('2026-09-01', '2026-09-14'):
        assert by_day[day]['period_id'] == period_a['id'], day
        assert by_day[day]['period_status'] == period_a['status'], day
    for day in _dates('2026-09-15', '2026-09-30'):
        assert by_day[day]['period_id'] == period_b['id'], day
    assert by_day['2026-09-07']['day_status'] == 'no_orders'
    assert by_day['2026-09-01']['day_status'] == 'no_plan'
    assert by_day['2026-09-01']['order_count'] == 1
    assert by_day['2026-09-16']['day_status'] == 'no_orders'
    chip_ids = {chip['id'] for chip in month['summary']['periods']}
    assert period_a['id'] in chip_ids
    assert period_b['id'] in chip_ids

    early = expect_ok(client.get(f'/rider-salary/calendar/{rider["id"]}/days/2026-09-07', headers=admin_token))
    assert early['period']['id'] == period_a['id']
    assert early['day_flag']['bad_weather'] is True
    assert early['day_flag']['high_temp'] is False
    assert early['day_flag']['remark'] == '甲站历史'
    assert early['day_status'] == 'no_orders'

    later = expect_ok(client.get(f'/rider-salary/calendar/{rider["id"]}/days/2026-09-16', headers=admin_token))
    assert later['period']['id'] == period_b['id']
    assert later['day_flag']['high_temp'] is True
    assert later['day_flag']['bad_weather'] is False
    assert later['day_flag']['remark'] == '乙站当前'
