! Copyright 2026 Logan W.
! SPDX-License-Identifier: Apache-2.0
!
! Calling libcft from Fortran, with iso_c_binding and nothing else.
!
!     make -C host fortran
!
! Fortran matters here more than its reputation suggests. An enormous
! amount of working numerical code is Fortran, it is where
! reproducibility complaints actually originate, and iso_c_binding
! makes this header callable without a wrapper generator, a build
! system, or a line of C.
!
! Note what does NOT happen below: real(c_double) is IEEE binary64
! with the layout this library already expects, so a native Fortran
! array is handed straight to c_loc() and used in place. There is no
! conversion step to get wrong, which is the point of specifying the
! buffers as dense little-endian interchange encodings rather than as
! a struct.
!
! STATUS: this example has not been compiled in the environment it was
! written in - no Fortran compiler was installed there - so unlike
! everything else under host/ it is unverified. `make -C host fortran`
! builds and runs it wherever gfortran exists, and that is the one
! command that turns this note into a result. Expected output:
!
!     1.0 * 0.5 + 1.0 = 1.5
!     2.0 * 0.25 + 1.0 = 1.5
!     3.0 * 2.0 + -6.0 = 0.0
!     4.0 * 8.0 + 0.0 = 32.0
!     flags 0x00

program vector_fma_fortran
    use, intrinsic :: iso_c_binding
    implicit none

    ! --- the contract, transcribed from host/include/cft.h ---
    interface
        function cft_open(artifact, idx, dev) bind(C, name="cft_open")
            import :: c_int, c_ptr
            type(c_ptr),    value      :: artifact   ! NULL = software
            integer(c_int), value      :: idx
            type(c_ptr),    intent(out) :: dev       ! cft_device **out
            integer(c_int)             :: cft_open
        end function cft_open

        subroutine cft_close(dev) bind(C, name="cft_close")
            import :: c_ptr
            type(c_ptr), value :: dev
        end subroutine cft_close

        function cft_run(dev, op, fmt, rnd, a, b, c, d, n, flags, bus) &
                bind(C, name="cft_run")
            import :: c_int, c_ptr, c_size_t
            type(c_ptr),       value :: dev
            integer(c_int),    value :: op, fmt, rnd
            type(c_ptr),       value :: a, b, c, d
            integer(c_size_t), value :: n
            type(c_ptr),       value :: flags, bus
            integer(c_int)           :: cft_run
        end function cft_run
    end interface

    ! cft_op, cft_format, cft_round - the values are normative, so a
    ! caller names them and never the register layout behind them.
    integer(c_int), parameter :: CFT_FMA  = 0
    integer(c_int), parameter :: CFT_FP64 = 1
    integer(c_int), parameter :: CFT_RNE  = 0

    type(c_ptr)                  :: dev
    integer(c_int)               :: st
    integer(c_int32_t), target   :: flags
    real(c_double), target       :: a(4), b(4), c(4), d(4)
    integer                      :: i

    a = [ 1.0d0, 2.0d0, 3.0d0, 4.0d0 ]
    b = [ 0.5d0, 0.25d0, 2.0d0, 8.0d0 ]
    c = [ 1.0d0, 1.0d0, -6.0d0, 0.0d0 ]
    d = 0.0d0
    flags = 0

    st = cft_open(c_null_ptr, 0_c_int, dev)
    if (st /= 0) then
        write (*, '(a,i0)') "cft_open failed: ", st
        stop 1
    end if

    st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, &
                 c_loc(a), c_loc(b), c_loc(c), c_loc(d), &
                 int(size(a), c_size_t), c_loc(flags), c_null_ptr)
    if (st /= 0) then
        write (*, '(a,i0)') "cft_run failed: ", st
        call cft_close(dev)
        stop 1
    end if

    do i = 1, size(a)
        write (*, '(f0.1," * ",f0.2," + ",f0.1," = ",f0.1)') &
            a(i), b(i), c(i), d(i)
    end do
    write (*, '("flags 0x",z2.2)') flags

    call cft_close(dev)
end program vector_fma_fortran
