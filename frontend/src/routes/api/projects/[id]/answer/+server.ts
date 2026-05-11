import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const POST: RequestHandler = async ({ params, request }) => {
	const body = await request.json();
	const response = await fetch(`${BACKEND}/api/projects/${params.id}/answer`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	const data = await response.json().catch(() => ({}));
	return json(data, { status: response.status });
};
