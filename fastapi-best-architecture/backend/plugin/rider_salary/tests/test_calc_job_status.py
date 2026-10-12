"""算薪作业终态：成功、失败、部分成功。"""

from backend.plugin.rider_salary.enums import CalcJobStatus
from backend.plugin.rider_salary.service.calc_job_service import resolve_calc_job_status


def test_resolve_calc_job_status() -> None:
    assert resolve_calc_job_status(success_count=2, failed_count=0, skipped=False) == CalcJobStatus.succeeded
    assert resolve_calc_job_status(success_count=0, failed_count=0, skipped=False) == CalcJobStatus.succeeded
    assert resolve_calc_job_status(success_count=1, failed_count=1, skipped=False) == CalcJobStatus.partial
    assert resolve_calc_job_status(success_count=0, failed_count=2, skipped=False) == CalcJobStatus.failed
    assert resolve_calc_job_status(success_count=0, failed_count=0, skipped=True) == CalcJobStatus.failed
    assert resolve_calc_job_status(success_count=3, failed_count=0, skipped=True) == CalcJobStatus.succeeded
    assert (
        resolve_calc_job_status(success_count=1, failed_count=0, skipped=False, crashed=True) == CalcJobStatus.partial
    )
