import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const DELETE: RequestHandler = async ({ params }) => {
	const projectId = params.id;
	const response = await fetch(`${BACKEND}/api/projects/${projectId}`, {
		method: 'DELETE'
	});
	const data = await response.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: response.status });
};
