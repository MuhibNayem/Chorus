import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ url }) => {
	const limit = url.searchParams.get('limit') || '50';
	const offset = url.searchParams.get('offset') || '0';

	const response = await fetch(`${BACKEND}/api/projects?limit=${limit}&offset=${offset}`);
	const data = await response.json();
	return json(data);
};

export const POST: RequestHandler = async ({ request }) => {
	const payload = await request.json().catch(() => ({}));
	const response = await fetch(`${BACKEND}/api/projects`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
	const data = await response.json();
	return json(data, { status: response.status });
};
