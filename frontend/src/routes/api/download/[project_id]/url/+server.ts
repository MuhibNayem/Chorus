import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params }) => {
	const projectId = params.project_id;
	const backendUrl = `${BACKEND}/api/download/${projectId}/url`;

	const response = await fetch(backendUrl);

	if (!response.ok) {
		const error = await response.text().catch(() => 'Failed to regenerate URL');
		return json({ error }, { status: response.status });
	}

	const data = await response.json();
	return json(data);
};
