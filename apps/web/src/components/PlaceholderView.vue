<script setup lang="ts">
defineProps<{ title: string; note: string }>()
</script>

<template>
  <section class="placeholder">
    <h1>{{ title }}</h1>
    <p>{{ note }}</p>
  </section>
</template>
