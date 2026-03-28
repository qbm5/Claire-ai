import { ref } from 'vue'
import { useToast } from './useToast'

export function useImageUpload(
  uploadFn: (id: string, file: File) => Promise<{ image_url: string }>,
  deleteFn: (id: string) => Promise<any>,
) {
  const { show: toast } = useToast()
  const imageFileInput = ref<HTMLInputElement>()
  const uploadingImage = ref(false)

  async function onImageSelected(event: Event, entityId: string, setUrl: (url: string) => void) {
    const file = (event.target as HTMLInputElement).files?.[0]
    if (!file) return
    uploadingImage.value = true
    try {
      const result = await uploadFn(entityId, file)
      if (result.image_url) {
        setUrl(result.image_url)
        toast('Image uploaded', 'success')
      }
    } catch (e: any) {
      toast(e.message || 'Failed to upload image', 'error')
    } finally {
      uploadingImage.value = false
      if (imageFileInput.value) imageFileInput.value.value = ''
    }
  }

  async function removeImage(entityId: string, clearUrl: () => void) {
    uploadingImage.value = true
    try {
      await deleteFn(entityId)
      clearUrl()
      toast('Image removed', 'success')
    } catch (e: any) {
      toast(e.message || 'Failed to remove image', 'error')
    } finally {
      uploadingImage.value = false
    }
  }

  return { imageFileInput, uploadingImage, onImageSelected, removeImage }
}
