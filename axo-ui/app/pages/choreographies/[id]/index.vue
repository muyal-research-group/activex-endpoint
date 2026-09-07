<template>
  <ChoreographyDesigner :choreography-id="choreographyId" />
</template>

<script setup lang="ts">
definePageMeta({
  key: to => to.fullPath,
})

const route = useRoute()
const choreographyId = computed(() => route.params.id as string)
</script>
