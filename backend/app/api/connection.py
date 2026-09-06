from fastapi import APIRouter, Request
from app.core.security import require_account
router=APIRouter(tags=['connection'])

@router.get('/connection')
def connection(request: Request):
    principal = require_account(request)
    settings=request.app.state.settings
    return {'authenticated':True, 'auth_mode': settings.auth_mode, 'account_id': principal.account_id, 'role': principal.role, 'model_id':settings.inference_model_id,
            'model_revision':settings.inference_model_revision,
            'heartbeat_interval_seconds':settings.heartbeat_interval_seconds,
            'worker_timeout_seconds':settings.worker_timeout_seconds,
            'task_types':['summarization','document-qa','information-extraction','coding-assistance'],
            'max_source_bytes':6000,'max_source_and_instruction_bytes':6500}
