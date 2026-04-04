#pragma once

#include <cstdint>
#include <vector>
#include <span>

/**
 * DTBLoader provides access to the embedded Device Tree Binary.
 * The DTB is compiled from little64.dts using dtc at build time.
 */
class DTBLoader {
public:
    /**
     * Get the embedded DTB bytes.
     * Returns an empty span if dtc was not available at build time.
     */
    static std::span<const uint8_t> getEmbeddedDTB();

    /**
     * Get the size of the embedded DTB in bytes.
     */
    static size_t getEmbeddedDTBSize();

private:
    DTBLoader() = delete;  // All methods are static
};
