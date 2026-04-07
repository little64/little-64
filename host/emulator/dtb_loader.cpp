#include "dtb_loader.hpp"

// Try to include the embedded DTB header if available
#if defined(__has_include)
  #if __has_include("little64_dtb_embed.hpp")
    #include "little64_dtb_embed.hpp"
    #define DTB_AVAILABLE 1
  #else
    #define DTB_AVAILABLE 0
  #endif
#else
  #define DTB_AVAILABLE 0
#endif

std::span<const uint8_t> DTBLoader::getEmbeddedDTB() {
#if DTB_AVAILABLE
  return std::span<const uint8_t>(embedded_dtb, embedded_dtb_len);
#else
    return std::span<const uint8_t>();  // Empty span
#endif
}

size_t DTBLoader::getEmbeddedDTBSize() {
#if DTB_AVAILABLE
  return embedded_dtb_len;
#else
    return 0;
#endif
}
