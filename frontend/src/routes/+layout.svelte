<script lang="ts">
	import '../app.css';
	import Sidebar from '$lib/components/layout/Sidebar.svelte';
	import TopBar from '$lib/components/layout/TopBar.svelte';

	let { children } = $props();
</script>

<div class="shell">
	<Sidebar />
	<div class="main">
		<TopBar />
		<div class="page">
			{@render children()}
		</div>
	</div>
</div>

<style>
	.shell {
		display: flex;
		min-height: 100vh;
	}

	.main {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.page {
		flex: 1;
		padding: 1.75rem;
	}
</style>