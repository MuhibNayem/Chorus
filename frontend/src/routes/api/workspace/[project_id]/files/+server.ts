import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params }) => {
	const response = await fetch(`${BACKEND}/api/workspace/${params.project_id}/files`);
	const data = await response.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: response.status });
};
