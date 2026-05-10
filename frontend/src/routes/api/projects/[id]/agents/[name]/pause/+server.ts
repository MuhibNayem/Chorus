import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const POST: RequestHandler = async ({ params, request }) => {
    const body = await request.json().catch(() => ({}));
    const response = await fetch(`${BACKEND}/api/projects/${params.id}/agents/${params.name}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    return json(data, { status: response.status });
};
