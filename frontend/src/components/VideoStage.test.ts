import { describe, expect, it } from 'vitest'

import type { LocateCandidate } from '../api'
import { candidateAtSourcePoint } from './VideoStage'

const candidates: LocateCandidate[] = [
  { box: [10, 20, 40, 80], score: 0.9 },
  { box: [100, 120, 140, 180], score: 0.8 },
]

describe('candidateAtSourcePoint', () => {
  it('returns the candidate whose rendered source box was clicked', () => {
    expect(candidateAtSourcePoint(candidates, { x: 25, y: 50 })).toEqual(
      candidates[0],
    )
    expect(candidateAtSourcePoint(candidates, { x: 120, y: 150 })).toEqual(
      candidates[1],
    )
  })

  it('returns null outside all candidate boxes', () => {
    expect(candidateAtSourcePoint(candidates, { x: 60, y: 100 })).toBeNull()
  })
})
